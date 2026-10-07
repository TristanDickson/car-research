"""One fact for every way of paying for a car: a sighting.

A sighting is a price one source showed for one subject, over the span of days
it stayed the same. The subject is a derivative (an offer on a car) or, for a
used car, the model and registration year the listing belongs to. Four routes:

    cash   an outright price
    pcp    a personal contract purchase example
    pch    a personal lease
    used   a used example's asking price

and sources are a dimension of their own (SOURCES maps a provider to one), so
the same derivative and route can be read source by source, and over time.

Everything here is pure. `cost` puts one sighting on the common footing of
model/deal_math (every payment discounted at the savings rate, the car's
expected end value credited back, spread over the term) with the residual the
used market gave *as of a date*, so a sighting from June is costed on what
June's used stock said, and today's on today's. `series` groups costed
sightings by subject, route and source; `current` picks the best per route and
source as of today. The exporter (pipeline/services/series.py) only loads rows
and writes files.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median
from typing import Callable

from model.deal_math import DEFAULT_BASIS, cash_metrics, pch_metrics, pcp_metrics, used_route

ROUTES = ("cash", "pcp", "pch", "used")
MIN_EVIDENCE = 3

# Provider → (source id, display name). Several providers read the same site.
SOURCES = {
    "carwow_deals": ("carwow", "Carwow"), "carwow_paste": ("carwow", "Carwow"), "carwow_used": ("carwow", "Carwow"),
    "hyundai_offers": ("hyundai", "Hyundai UK"), "ncd": ("ncd", "New Car Discount"), "leaseloco": ("leaseloco", "LeaseLoco"),
    "rrg": ("rrg", "RRG"), "manual_seed": ("manual", "Hand-entered"),
    "cinch_used": ("cinch", "cinch"), "motorpoint_used": ("motorpoint", "Motorpoint"),
}


def source_of(provider: str) -> str:
    return SOURCES.get(provider, (provider, provider))[0]


def source_name(source: str) -> str:
    return next((name for sid, name in SOURCES.values() if sid == source), source)


@dataclass(frozen=True)
class Sighting:
    key: str              # the offer key, or the used listing key
    route: str            # one of ROUTES
    source: str           # a source id (source_of)
    model: str            # "make/model" catalogue slugs
    car_id: str | None    # the derivative, where the sighting names one
    seen_from: str        # ISO date the state was first seen
    seen_to: str          # ISO date it was last confirmed (>= seen_from)
    present: bool
    deal: dict            # the price-bearing fields: an offer payload, or {price, year, mileage, vrm}
    seller: str | None = None


def subject(s: Sighting) -> str:
    """What a series is about: the derivative, or the model for used stock."""
    return s.car_id if s.route != "used" and s.car_id else f"model:{s.model}"


def term_years(basis: dict) -> int:
    return max(1, round((basis.get("term_months") or DEFAULT_BASIS["term_months"]) / 12))


def residual_at(used: list[Sighting]) -> Callable[[str, int, date], tuple[float, int] | None]:
    """(model, registration year, date) → (median asking price, n) of the
    model's used examples of that year listed on that date, or None below
    MIN_EVIDENCE. The same car on two sites (same registration, or the same
    mileage where none is printed) counts once."""
    by: dict[tuple[str, int], list[Sighting]] = {}
    for s in used:
        if s.present and s.deal.get("year") and s.deal.get("price"):
            by.setdefault((s.model, int(s.deal["year"])), []).append(s)

    def at(model: str, year: int, d: date) -> tuple[float, int] | None:
        iso = d.isoformat()
        live = [s for s in by.get((model, year), ()) if s.seen_from[:10] <= iso <= s.seen_to[:10]]
        # A site that prints no registration still prints the mileage: the same
        # mileage as a registered listing is the same car.
        plate_by_mileage = {s.deal.get("mileage"): s.deal["vrm"] for s in live if s.deal.get("vrm") and s.deal.get("mileage")}
        best: dict[object, float] = {}
        for s in live:
            car = s.deal.get("vrm") or plate_by_mileage.get(s.deal.get("mileage")) or ("mi", s.deal.get("mileage") or s.key)
            best[car] = min(best.get(car, float("inf")), float(s.deal["price"]))
        prices = sorted(best.values())
        return (round(median(prices)), len(prices)) if len(prices) >= MIN_EVIDENCE else None

    return at


def floor_gfv_at(offers: list[Sighting]) -> Callable[[str | None, date], float | None]:
    """(car, date) → the highest GFV any lender guaranteed for the car on that
    date: the floor a cash buyer could count on."""
    by: dict[str, list[Sighting]] = {}
    for s in offers:
        if s.route == "pcp" and s.present and s.car_id and s.deal.get("gfv"):
            by.setdefault(s.car_id, []).append(s)

    def at(car_id: str | None, d: date) -> float | None:
        iso = d.isoformat()
        vals = [float(s.deal["gfv"]) for s in by.get(car_id or "", ()) if s.seen_from[:10] <= iso <= s.seen_to[:10]]
        return max(vals) if vals else None

    return at


@dataclass(frozen=True)
class Costed:
    sighting: Sighting
    as_of: str                      # the date the residual evidence was read
    headline: float | None          # what the source printed: a price, or a monthly
    true_monthly: float | None
    true_monthly_floor: float | None
    pv_cost: float | None
    expected_value_at_end: float | None
    residual_source: str | None     # used-market | gfv-grown | assumption
    basis_rate: float               # the savings rate every point is discounted at


def cost(s: Sighting, basis: dict, residual: Callable, floor_gfv: Callable, as_of: date) -> Costed | None:
    """One sighting on the common footing, with the used market read as of `as_of`."""
    b = {**DEFAULT_BASIS, **(basis or {})}
    ty = term_years(b)
    if s.route == "used":
        price, year = s.deal.get("price"), s.deal.get("year")
        if not price:
            return None
        ev = residual(s.model, int(year) - ty, as_of) if year else None
        m = used_route(float(price), (as_of.year - int(year)) if year else None, b, ev[0] if ev else None)
        return Costed(s, as_of.isoformat(), float(price), m["true_monthly"], None, m["pv_cost"], m["expected_value_at_end"],
                      m["residual_source"], b["savings_rate_apr"])
    ev = residual(s.model, as_of.year - ty, as_of)
    residuals = {s.car_id: {"value": ev[0], "source": "used-market", "n": ev[1]}} if ev and s.car_id else None
    d = {**s.deal, "id": s.key, "car_id": s.car_id, "finance_type": s.route, "status": s.deal.get("status") or "live"}
    try:
        if s.route == "pcp":
            m = pcp_metrics(d, None, b, residuals, floor_gfv(s.car_id, as_of))
            headline = m.get("monthly_payment")
        elif s.route == "pch":
            m = pch_metrics(d, b)
            headline = m.get("effective_monthly") or d.get("monthly_rental")
        elif s.route == "cash":
            m = cash_metrics(d, b, floor_gfv(s.car_id, as_of), residuals)
            headline = d.get("vehicle_price")
        else:
            return None
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None
    if m.get("skipped") or m.get("true_monthly") is None:
        return None
    return Costed(s, as_of.isoformat(), headline, m["true_monthly"], m.get("true_monthly_floor"), m.get("pv_cost"),
                  m.get("expected_value_at_end"), m.get("residual_source"), b["savings_rate_apr"])


def cost_all(sightings: list[Sighting], basis: dict, as_of: date | None = None) -> list[Costed]:
    """Every present sighting costed, each as of its own first day (history) or
    as of one date (`as_of`, for what things cost today)."""
    used = [s for s in sightings if s.route == "used"]
    residual = residual_at(used)
    floor = floor_gfv_at([s for s in sightings if s.route != "used"])
    out = []
    for s in sightings:
        if not s.present:
            continue
        c = cost(s, basis, residual, floor, as_of or date.fromisoformat(s.seen_from[:10]))
        if c:
            out.append(c)
    return out


def _point(c: Costed) -> dict:
    s = c.sighting
    return {"from": s.seen_from[:10], "to": s.seen_to[:10], "key": s.key, "route": s.route, "source": s.source, "seller": s.seller, "headline": c.headline,
            "true_monthly": c.true_monthly, "true_monthly_floor": c.true_monthly_floor, "residual_source": c.residual_source,
            "as_of": c.as_of}


def _slim(p: dict) -> dict:
    """A series point without what the series itself already says."""
    return {k: v for k, v in p.items() if k not in ("route", "source", "as_of")}


def _best_steps(cs: list[Costed]) -> list[dict]:
    """For a crowd of overlapping sightings (a model's used stock), the cheapest
    true monthly on each day the set changes, as flat steps."""
    bounds = sorted({c.sighting.seen_from[:10] for c in cs} | {c.sighting.seen_to[:10] for c in cs})
    steps: list[dict] = []
    for i, d in enumerate(bounds):
        live = [c for c in cs if c.sighting.seen_from[:10] <= d <= c.sighting.seen_to[:10] and c.true_monthly is not None]
        if not live:
            continue
        best = min(live, key=lambda c: c.true_monthly)
        to = bounds[i + 1] if i + 1 < len(bounds) else d
        if steps and steps[-1]["key"] == best.sighting.key and steps[-1]["true_monthly"] == best.true_monthly:
            steps[-1]["to"] = to
            continue
        steps.append({**_point(best), "from": d, "to": to, "n": len(live)})
    return steps


def series(costed: list[Costed]) -> list[dict]:
    """Costed sightings grouped by subject, route and source: an offer's
    sightings as flat spans; a model's used stock as the cheapest example day
    by day."""
    groups: dict[tuple[str, str, str], list[Costed]] = {}
    for c in costed:
        groups.setdefault((subject(c.sighting), c.sighting.route, c.sighting.source), []).append(c)
    out = []
    for (subj, route, src), cs in sorted(groups.items()):
        cs.sort(key=lambda c: (c.sighting.seen_from, c.sighting.key))
        first = cs[0].sighting
        out.append({"id": f"{subj}|{route}|{src}", "subject": subj, "car_id": first.car_id if route != "used" else None,
                    "model": first.model, "route": route, "source": src, "source_name": source_name(src),
                    "points": [_slim(p) for p in (_best_steps(cs) if route == "used" else [_point(c) for c in cs])]})
    return out


def residual_series(used: list[Sighting], today: date) -> list[dict]:
    """What the used market said a model's cars of each registration year were
    worth, month by month: the evidence behind every point's end value."""
    residual = residual_at(used)
    keys = sorted({(s.model, int(s.deal["year"])) for s in used if s.present and s.deal.get("year") and s.deal.get("price")})
    if not keys:
        return []
    start = date.fromisoformat(min(s.seen_from[:10] for s in used))
    dates = []
    d = date(start.year, start.month, 1)
    while d <= today:
        dates.append(d)
        d = (d.replace(day=1) + timedelta(days=32)).replace(day=1)
    if not dates or dates[-1] != today:
        dates.append(today)
    out = []
    for model, year in keys:
        pts = [{"date": d.isoformat(), "median": ev[0], "n": ev[1]} for d in dates if (ev := residual(model, year, d))]
        if pts:
            out.append({"model": model, "year": year, "points": pts})
    return out


def current(costed_today: list[Costed], today: date, stale_days: int) -> dict[str, dict[str, dict[str, dict]]]:
    """subject → route → source → the cheapest sighting still current (last
    confirmed within `stale_days`), costed as of today."""
    cutoff = (today - timedelta(days=stale_days)).isoformat()
    out: dict[str, dict[str, dict[str, dict]]] = {}
    for c in costed_today:
        s = c.sighting
        if s.seen_to[:10] < cutoff or c.true_monthly is None:
            continue
        slot = out.setdefault(subject(s), {}).setdefault(s.route, {})
        cur = slot.get(s.source)
        if cur is None or c.true_monthly < cur["true_monthly"]:
            slot[s.source] = {**_point(c), "source_name": source_name(s.source),
                              "age_days": (today - date.fromisoformat(s.seen_to[:10])).days}
    return out


def best_by_route(routes: dict[str, dict[str, dict]]) -> dict[str, dict]:
    """route → the cheapest source's figure."""
    return {route: min(by_src.values(), key=lambda p: p["true_monthly"]) for route, by_src in routes.items() if by_src}
