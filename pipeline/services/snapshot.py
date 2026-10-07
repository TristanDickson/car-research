"""Static snapshot exporter: Gold → a directory of JSON the SPA reads.

Layout (schema_version 4):
    manifest.json       {schema_version, generated_at, counts, runs}
    cars.json           [car + deal_summary]; hand-curated and generated (auto: true); what every page loads
    details.json        {car id: used stock by year, spec rows, the cross-check, the seed's brief check}; on demand
    offers.json         [latest observation of each offer + metrics + freshness]
    requirements.json   the requirements document as-is
    data.json           providers, recent runs, unmapped trims, offer states, catalogue counts
    specs.json          every scraped variant: equipment list, canonical flags, numbers, image
    models.json         the catalogue: every electric model Carwow lists, with what we hold for it
    used.json           used stock per model (Carwow, cinch, Motorpoint): price, year, mileage, derivative, site
    series.json         every sighting by subject, route and source, costed as of its day (model/sightings.py)
    residuals.json      what the used market said each model's cars of each year were worth, month by month

An offer's current values are its latest observation. Freshness is derived here
from the observation history, never typed by hand:
    state   gone (latest check did not find it) | expired (valid_to passed or the
            source said so) | otherwise the observed status (live, lead, ...)
    stale   an active offer whose last sighting is older than STALE_DAYS
Finance maths is computed here, once, so the browser never needs its own copy.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from statistics import median

from model.deal_math import compute, used_route
from model.sightings import best_by_route, trend
from pipeline.db import ROOT
from pipeline.services import facts
from pipeline.services import series as series_svc

IMAGE_EXTS = ("jpg", "jpeg", "png", "webp")

# Bump on any incompatible shape change; the SPA warns loudly on skew.
SCHEMA_VERSION = "6"

# Spec payload fields kept in data/history/specs.jsonl but not shipped in specs.json.
SPEC_PRIVATE = ("raw_numbers", "description", "observed_at")

# Observed statuses that count as "an offer you could act on today".
ACTIVE_STATUSES = {"live", "lead", "derived", "illustrative"}
STALE_DAYS = 14
HISTORY_FIELDS = ("monthly_payment", "vehicle_price", "apr", "gfv", "initial_rental", "monthly_rental")


def _write(path: Path, obj, pretty: bool = False) -> None:
    """Compact JSON by default: the big arrays are fetched by the browser, not read by people."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False) if pretty else json.dumps(obj, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
    path.write_text(text + "\n", encoding="utf-8")


def evaluate_hard(requirements: dict, car: dict) -> dict:
    """Check a car against the hard rules. Rules with applies_to == 'deal' are
    skipped; a rule whose field the car does not carry is 'unknown', not a fail."""
    failures: list[str] = []
    unknown: list[str] = []
    for rule in requirements.get("hard", []):
        if rule.get("applies_to") == "deal":
            continue
        value = car.get(rule.get("field"))
        if value is None or value == "unknown":
            unknown.append(rule["id"])
            continue
        op, want = rule.get("op"), rule.get("value")
        if op == "==":
            ok = value == want
        elif op == "in":
            ok = value in want
        elif op == ">=":
            ok = value >= want
        elif op == "<=":
            ok = value <= want
        else:
            unknown.append(rule["id"])
            continue
        if not ok:
            failures.append(rule["id"])
    return {"passes": not failures, "failures": failures, "unknown": unknown}


def _is_current(o: dict) -> bool:
    f = o["freshness"]
    return f["state"] in ACTIVE_STATUSES and not f["stale"]


ROUTE_POINT_KEYS = ("key", "source", "source_name", "seller", "true_monthly", "true_monthly_floor", "headline", "end_value",
                    "residual_source", "age_days", "to")


def _slim_routes(routes: dict[str, dict[str, dict]]) -> dict[str, dict[str, dict]]:
    """route → source → the fields a card or table shows."""
    return {route: {src: {k: p.get(k) for k in ROUTE_POINT_KEYS} for src, p in by_src.items()} for route, by_src in routes.items()}


def _slim_stock(stock: dict | None) -> dict | None:
    """What every page needs of a model's used stock; details.json has the rest."""
    if not stock:
        return None
    ch = stock["cheapest"]
    return {"count": stock["count"], "sources": stock.get("sources"), "residual": stock.get("residual"),
            "cheapest": {k: ch.get(k) for k in ("listing_key", "price_gbp", "year", "mileage", "source", "url")}}


# A hand-curated car's own tri-state fields, as the canonical flags the specs use.
CAR_FIELD_FLAGS = {"heat_pump": "heat_pump", "internal_v2l": "v2l_internal", "external_v2l": "v2l_external"}


def car_flags(car: dict, specs: list[dict]) -> dict[str, str]:
    """The car's equipment as canonical flags for the query: what its spec rows
    list (standard beats option), with its own curated fields filling gaps
    ('pack' and 'option' are listed, 'standard' is standard). Unlisted is the
    default and is not written."""
    out = {k: v for k, v in merged_flags(specs).items() if v}
    for field, flag in CAR_FIELD_FLAGS.items():
        v = car.get(field)
        if flag not in out and v in ("standard", "pack", "option"):
            out[flag] = "standard" if v == "standard" else "option"
        if out.get(flag) and v in ("standard", "pack", "option") and out[flag] != "standard" and v == "standard":
            out[flag] = "standard"
    if any(out.get(k) for k in ("v2l_internal", "v2l_external")) and not out.get("v2l_any"):
        out["v2l_any"] = "standard" if "standard" in (out.get("v2l_internal"), out.get("v2l_external")) else "option"
    return out


def merged_flags(specs: list[dict]) -> dict[str, str | None]:
    """One flag set per car from its spec rows: standard beats option beats unlisted."""
    rank = {"standard": 2, "option": 1}
    out: dict[str, str | None] = {}
    for sp in specs:
        for k, v in (sp.get("flags") or {}).items():
            if rank.get(v, 0) > rank.get(out.get(k), 0):
                out[k] = v
            else:
                out.setdefault(k, v)
    return out


def deal_summary(offers: list[dict], metrics_by_id: dict[str, dict], used: dict | None = None,
                 routes: dict[str, dict[str, dict]] | None = None) -> dict:
    """The car's headline figures. `routes` (route → source → the cheapest
    current sighting costed as of today, from model/sightings) is the one cost
    model; the per-offer metrics only decorate the offer table."""
    current = [o for o in offers if _is_current(o)]
    cash = [o for o in current if o["finance_type"] == "cash" and o.get("vehicle_price")]
    best_cash = min(cash, key=lambda o: o["vehicle_price"]) if cash else None

    pcps = []
    for o in current:
        m = metrics_by_id.get(o["id"])
        if o["finance_type"] == "pcp" and m and "skipped" not in m and (o.get("customer_deposit") or 0) == 0:
            pcps.append((o, m))
    best_pcp = min(pcps, key=lambda om: om[1]["monthly_payment"]) if pcps else None

    pchs = [(o, metrics_by_id[o["id"]]) for o in current
            if o["finance_type"] == "pch" and o["id"] in metrics_by_id and "skipped" not in metrics_by_id[o["id"]]]
    best_pch = min(pchs, key=lambda om: om[1]["effective_monthly"]) if pchs else None

    def age(o):
        return o["freshness"]["age_days"] if o else None

    # True monthly: every current sighting on one footing (model/sightings), best per route and per source.
    routes = routes or {}
    true_by_route: dict[str, dict] = {}
    for route, p in best_by_route(routes).items():
        true_by_route[route] = {"offer_id": p["key"], "true_monthly": p["true_monthly"], "true_monthly_floor": p.get("true_monthly_floor"),
                                "age_days": p.get("age_days"), "source": p.get("source"), "headline": p.get("headline")}
    best_true = min(true_by_route.items(), key=lambda kv: kv[1]["true_monthly"]) if true_by_route else None

    return {
        "offers": len(offers),
        "current_offers": len(current),
        "best_true_monthly": best_true[1]["true_monthly"] if best_true else None,
        "best_true_route": best_true[0] if best_true else None,
        "best_true_offer_id": best_true[1]["offer_id"] if best_true else None,
        "true_monthly_by_route": true_by_route,
        "routes": routes,
        "best_cash_price": best_cash["vehicle_price"] if best_cash else None,
        "best_cash_offer_id": best_cash["id"] if best_cash else None,
        "best_cash_age_days": age(best_cash),
        "best_pcp_monthly": best_pcp[1]["monthly_payment"] if best_pcp else None,
        "best_pcp_offer_id": best_pcp[0]["id"] if best_pcp else None,
        "best_pcp_age_days": age(best_pcp[0]) if best_pcp else None,
        "best_pcp_total": best_pcp[1].get("paid_if_handed_back") if best_pcp else None,
        "best_pcp_dealer": (best_pcp[0].get("dealer") or best_pcp[0].get("source")) if best_pcp else None,
        "best_pch_total": best_pch[1].get("total_cost") if best_pch else None,
        "best_pch_dealer": (best_pch[0].get("dealer") or best_pch[0].get("source")) if best_pch else None,
        "best_cash_dealer": (best_cash.get("dealer") or best_cash.get("source")) if best_cash else None,
        "best_pch_effective_monthly": best_pch[1]["effective_monthly"] if best_pch else None,
        "best_pch_offer_id": best_pch[0]["id"] if best_pch else None,
        "best_pch_age_days": age(best_pch[0]) if best_pch else None,
    }


def load_picks(root: Path) -> dict[str, list[dict]]:
    """Household verdicts (data/seed/picks.json): our own decisions, not sourced
    data, so they bypass the medallion and ride along at export."""
    path = root / "data" / "seed" / "picks.json"
    if not path.exists():
        return {}
    out: dict[str, list[dict]] = {}
    for pick in json.loads(path.read_text(encoding="utf-8")).get("picks", []):
        out.setdefault(pick["car_id"], []).append({k: pick.get(k) for k in ("who", "verdict", "note")})
    return out


def car_image(root: Path, car: dict, spec: dict | None = None) -> str | None:
    """A committed photo under web/public/images/cars/<id>.<ext> wins; else the
    car record's image_url; else the mapped spec source's image (Carwow renders
    one per derivative); else None (the SPA shows a placeholder)."""
    for ext in IMAGE_EXTS:
        if (root / "web" / "public" / "images" / "cars" / f'{car["id"]}.{ext}').exists():
            return f'/images/cars/{car["id"]}.{ext}'
    return car.get("image_url") or (spec or {}).get("image_url")


SPEC_CHECKS = (
    # (car field, flag, label)
    ("heat_pump", "heat_pump", "Heat pump"),
    ("internal_v2l", "v2l_internal", "Internal V2L"),
    ("external_v2l", "v2l_external", "External V2L"),
)


def load_specs(conn: sqlite3.Connection) -> list[dict]:
    """Every scraped variant: the payload plus the gold columns the app filters on."""
    out = []
    for r in conn.execute("SELECT * FROM specs ORDER BY make, model, trim, spec_key"):
        p = json.loads(r["payload"])
        p.update({
            "spec_key": r["spec_key"], "provider": r["source"], "car_id": r["car_id"],
            "first_seen_at": r["first_seen_at"], "last_seen_at": r["last_seen_at"], "changed_at": r["changed_at"],
            "image_url": r["image_url"] or p.get("image_url"),
        })
        p.pop("car_ref", None)
        out.append(p)
    return out


def spec_check(car: dict, specs: list[dict]) -> dict:
    """Hand-entered tri-state fields against what the scraped sources list.
    'standard'/'pack'/'option' vs flag 'standard'/'option'; None from a source
    means 'not listed', which is not a contradiction."""
    rows = []
    for field, flag, label in SPEC_CHECKS:
        hand = car.get(field)
        for sp in specs:
            seen = (sp.get("flags") or {}).get(flag)
            if seen is None:
                verdict = "not listed"
            elif hand in ("standard",) and seen == "standard":
                verdict = "agrees"
            elif hand in ("pack", "option") and seen in ("option", "standard"):
                verdict = "agrees"  # we specify the car with it fitted; the source lists it as fitted or fittable
            elif hand == "none" and seen:
                verdict = "source lists it"
            elif hand in (None, "unknown"):
                verdict = f"source says {seen}"
            else:
                verdict = "differs"
            rows.append({"field": field, "label": label, "hand": hand, "source": sp["provider"], "seen": seen, "verdict": verdict,
                         "spec_key": sp["spec_key"]})
    return {"rows": rows, "disagreements": sum(1 for r in rows if r["verdict"] in ("differs", "source lists it"))}


def specs_by_make(specs: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for sp in specs:
        if sp.get("image_url"):
            out.setdefault((sp.get("make") or "").lower(), []).append(sp)
    return out


def fallback_image(car: dict, by_make: dict[str, list[dict]]) -> str | None:
    """A Carwow render for the same make + model and, if possible, the same trim word,
    for cars whose exact derivative is not on the spec page (pack variants, options,
    a derivative only a deals page printed)."""
    make, model = (car.get("make") or "").lower(), (car.get("model") or "").lower()
    trim = (car.get("trim") or "").lower()
    slug = car.get("model_slug")
    same_model = [sp for sp in by_make.get(make, [])
                  if (slug and sp.get("model_slug") == slug)
                  or model in (sp.get("model") or "").lower() or (sp.get("model") or "").lower() in model]
    for sp in same_model:
        if (sp.get("trim") or "").lower() and (sp.get("trim") or "").lower() in trim:
            return sp["image_url"]
    return same_model[0]["image_url"] if same_model else None


def load_used(conn: sqlite3.Connection) -> list[dict]:
    """Used stock, every listing ever seen (present = still listed)."""
    try:
        rows = conn.execute("SELECT * FROM used_listings ORDER BY make_slug, model_slug, year, price_gbp").fetchall()
    except sqlite3.OperationalError:
        return []
    out = []
    for r in rows:
        p = json.loads(r["payload"])
        out.append({"listing_key": r["listing_key"], "provider": r["source"], "make": r["make"], "make_slug": r["make_slug"],
                    "model": r["model"], "model_slug": r["model_slug"], "car_id": r["car_id"], "price_gbp": r["price_gbp"],
                    "year": r["year"], "mileage": r["mileage"], "present": bool(r["present"]),
                    "first_seen_at": r["first_seen_at"], "last_seen_at": r["last_seen_at"],
                    "derivative": p.get("derivative"), "town": p.get("town"), "url": p.get("source_url"),
                    "image_url": p.get("image_url"), "source": p.get("source"), "vrm": p.get("vrm")})
    return out


def car_slugs(car: dict, specs_by_car: dict[str, list[dict]]) -> tuple[str, str]:
    """(make_slug, model_slug) for any car: generated cars carry them, a
    hand-curated car's mapped Carwow spec knows them."""
    via = next((sp for sp in specs_by_car.get(car["id"], []) if sp.get("model_slug")), {})
    return ((car.get("make_slug") or via.get("make_slug") or car.get("make") or "").lower(),
            car.get("model_slug") or via.get("model_slug") or "")


MIN_USED_EVIDENCE = 3


def _vrm(l: dict) -> str | None:
    v = re.sub(r"\s+", "", l.get("vrm") or "").upper()
    return v or None


def dedupe_listings(listings: list[dict]) -> list[dict]:
    """One row per car across the sources. A car listed on two sites is the
    same car when the registrations match, or, where a site prints none, when
    the registration year and mileage match a registered listing's or each
    other's. The cheapest listing still on sale stands for the car and names
    every site under 'sources'."""
    by_vrm: dict[str, list[dict]] = {}
    for l in listings:
        if _vrm(l):
            by_vrm.setdefault(_vrm(l), []).append(l)
    ym_of_vrm: dict[tuple, str] = {}
    for v, members in by_vrm.items():
        for l in members:
            if l.get("year") and l.get("mileage"):
                ym_of_vrm.setdefault((l["year"], l["mileage"]), v)
    by_ym: dict[tuple, list[dict]] = {}
    rest: list[list[dict]] = []
    for l in listings:
        if _vrm(l):
            continue
        ym = (l["year"], l["mileage"]) if l.get("year") and l.get("mileage") else None
        if ym and ym in ym_of_vrm:
            by_vrm[ym_of_vrm[ym]].append(l)
        elif ym:
            by_ym.setdefault(ym, []).append(l)
        else:
            rest.append([l])
    out: list[dict] = []
    for members in [*by_vrm.values(), *by_ym.values(), *rest]:
        live = [l for l in members if l.get("present")] or members
        best = min(live, key=lambda l: l.get("price_gbp") or float("inf"))
        sources = sorted({l.get("source") or l.get("provider") or "?" for l in members})
        out.append(dict(best, sources=sources) if len(members) > 1 else best)
    return out


def used_evidence(listings: list[dict], today: date, basis: dict) -> dict:
    """What a model's used stock says a car is worth after the standard term:
    the median asking price of examples registered term-years ago, when there
    are at least MIN_USED_EVIDENCE of them. Also the medians per registration
    year, for the car page."""
    term_years = max(1, round((basis.get("term_months") or 37) / 12))
    target_year = today.year - term_years
    present = [l for l in dedupe_listings(listings) if l["present"] and l.get("price_gbp") and l.get("year")]
    by_year: dict[int, dict] = {}
    for y in sorted({l["year"] for l in present}):
        prices = sorted(l["price_gbp"] for l in present if l["year"] == y)
        by_year[y] = {"n": len(prices), "median": round(median(prices)), "min": prices[0]}
    ev = by_year.get(target_year)
    residual = None
    if ev and ev["n"] >= MIN_USED_EVIDENCE:
        residual = {"value": ev["median"], "source": "used-market", "n": ev["n"], "year": target_year}
    return {"by_year": by_year, "residual": residual, "target_year": target_year, "term_years": term_years}


def used_summary(listings: list[dict], evidence: dict, basis: dict, today: date) -> dict | None:
    """The 'buy used' route for a model: its cheapest listing on sale now, costed
    like the other routes (price now, sold after the term at what the model's
    stock says a car that much older asks today)."""
    present = [l for l in dedupe_listings(listings) if l["present"] and l.get("price_gbp")]
    if not present:
        return None
    cheapest = min(present, key=lambda l: l["price_gbp"])
    sources: dict[str, int] = {}
    for l in listings:
        if l["present"] and l.get("price_gbp"):
            sources[l.get("source") or l.get("provider") or "?"] = sources.get(l.get("source") or l.get("provider") or "?", 0) + 1
    age = (today.year - cheapest["year"]) if cheapest.get("year") else None
    v_end = None
    if age is not None:
        later = evidence["by_year"].get(cheapest["year"] - evidence["term_years"])
        if later and later["n"] >= MIN_USED_EVIDENCE:
            v_end = later["median"]
    route = used_route(cheapest["price_gbp"], age, basis, v_end)
    return {
        "count": len(present),
        "cheapest": {k: cheapest.get(k) for k in ("listing_key", "price_gbp", "year", "mileage", "derivative", "town", "url", "image_url", "source", "sources")}
                    | {"age_days": (today - date.fromisoformat(cheapest["last_seen_at"][:10])).days},
        "sources": sources,
        "by_year": evidence["by_year"], "residual": evidence["residual"], "route": route,
    }


def load_models(conn: sqlite3.Connection) -> list[dict]:
    """The catalogue (electric models only), with per-model counts of what we hold."""
    try:
        rows = conn.execute("SELECT * FROM models WHERE electric=1 ORDER BY make, model").fetchall()
    except sqlite3.OperationalError:
        return []
    return [{"slug": r["slug"], "make": r["make"], "model": r["model"],
             "make_name": r["make_name"], "model_name": r["model_name"],
             "has_deals": bool(r["has_deals"]), "has_specs": bool(r["has_specs"]),
             "first_seen_at": r["first_seen_at"], "last_seen_at": r["last_seen_at"]} for r in rows]


def load_cars(conn: sqlite3.Connection) -> list[dict]:
    return [json.loads(r["payload"]) for r in conn.execute("SELECT payload FROM cars ORDER BY id")]


def load_requirements(conn: sqlite3.Connection) -> dict:
    row = conn.execute("SELECT payload FROM requirements WHERE id = 1").fetchone()
    return json.loads(row["payload"]) if row else {}


def _freshness(obs: list[sqlite3.Row], payload: dict, today: date) -> dict:
    latest = obs[-1]
    seen = [o for o in obs if o["present"]]
    last_seen = max((o["confirmed_at"] or o["observed_at"]) for o in seen) if seen else None
    age = (today - date.fromisoformat(last_seen[:10])).days if last_seen else None
    if not latest["present"]:
        state = "gone"
    elif payload.get("valid_to") and payload["valid_to"] < today.isoformat():
        state = "expired"
    else:
        state = latest["status"]
    stale = state in ACTIVE_STATUSES and age is not None and age > STALE_DAYS
    history = []
    for o in obs:
        p = json.loads(o["payload"])
        history.append({"observed_at": o["observed_at"], "confirmed_at": o["confirmed_at"], "present": bool(o["present"]),
                        "source": o["source"], **{k: p.get(k) for k in HISTORY_FIELDS if p.get(k) is not None}})
    return {
        "state": state,
        "stale": stale,
        "age_days": age,
        "first_seen_at": obs[0]["observed_at"],
        "last_seen_at": last_seen,
        "last_checked_at": latest["confirmed_at"] or latest["observed_at"],
        "observations": len(obs),
        "present": bool(latest["present"]),
        "history": history,
    }


def latest_offers(conn: sqlite3.Connection, today: date | None = None) -> list[dict]:
    """One dict per offer key: the latest observation's payload (id = offer key)
    plus a `freshness` block derived from the whole history."""
    today = today or datetime.now(timezone.utc).date()
    rows = conn.execute(
        "SELECT * FROM offer_observations ORDER BY offer_key, observed_at, id"
    ).fetchall()
    groups: dict[str, list[sqlite3.Row]] = {}
    for r in rows:
        groups.setdefault(r["offer_key"], []).append(r)
    out = []
    for key, obs in groups.items():
        payload = json.loads(obs[-1]["payload"])
        payload["id"] = key
        payload["car_id"] = obs[-1]["car_id"]
        payload["provider"] = obs[-1]["source"]
        payload["freshness"] = _freshness(obs, payload, today)
        out.append(payload)
    out.sort(key=lambda o: (o["freshness"]["last_checked_at"], o["id"]))
    return out


def latest_runs(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    rows = conn.execute(
        "SELECT id, source, capability, target, started_at, finished_at, status, artifacts, records, unmapped, errors "
        "FROM runs ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


def unmapped_trims(conn: sqlite3.Connection) -> list[dict]:
    """Broker rows that resolved to no car: 'unmapped' (nothing fits) and
    'conflict' (twins the rules refuse to guess between), with the evidence."""
    rows = conn.execute(
        "SELECT source, source_key, label, example_url, first_seen_at, last_seen_at, status, method, evidence FROM trim_map "
        "WHERE status IN ('unmapped', 'conflict') ORDER BY status, source, source_key"
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["evidence"] = json.loads(d["evidence"]) if d.get("evidence") else None
        out.append(d)
    return out


def resolution_methods(conn: sqlite3.Connection) -> dict[str, int]:
    """How the resolved rows were resolved, for the Data page."""
    out: dict[str, int] = {}
    for method, status, n in conn.execute(
            "SELECT method, status, COUNT(*) FROM trim_map WHERE status IN ('mapped', 'auto') GROUP BY method, status"):
        key = method or ("manual" if status == "mapped" else "cap-id")
        out[key] = out.get(key, 0) + n
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def _provider_blurb(name: str) -> str:
    """First line of the provider module's docstring, for the Data page."""
    import importlib

    try:
        doc = importlib.import_module(f"pipeline.providers.{name}").__doc__ or ""
    except ImportError:
        return ""
    return doc.strip().splitlines()[0] if doc.strip() else ""


def export_snapshot(conn: sqlite3.Connection, out_dir: Path | str, generated_at: str | None = None,
                    root: Path = ROOT) -> dict:
    from pipeline.providers import PROVIDERS

    out = Path(out_dir)
    picks = load_picks(root)
    generated_at = generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    today = date.fromisoformat(generated_at[:10])

    cars = load_cars(conn)
    offers = latest_offers(conn, today)
    requirements = load_requirements(conn)
    specs = load_specs(conn)
    models = load_models(conn)
    used = load_used(conn)
    specs_by_car: dict[str, list[dict]] = {}
    for sp in specs:
        if sp.get("car_id"):
            specs_by_car.setdefault(sp["car_id"], []).append(sp)
    renders = specs_by_make(specs)
    # Facts the cars lack, from the evidence we hold, each field naming its source (services/facts.py).
    facts.overlay_curated(cars)
    facts.overlay_evdb(cars, [sp for sp in specs if sp.get("provider") == "evdb"], models)

    # The used market, per model: the residual evidence the true-monthly needs and the 'buy used' route.
    basis = {"term_months": 37, "savings_rate_apr": 0.04, "residual_pct_of_list": 0.45, "residual_at_months": 36,
             **(requirements.get("quoting_basis") or {})}
    used_by_model: dict[tuple[str, str], list[dict]] = {}
    for l in used:
        used_by_model.setdefault(((l.get("make_slug") or "").lower(), l.get("model_slug") or ""), []).append(l)
    evidence = {k: used_evidence(v, today, basis) for k, v in used_by_model.items()}
    used_summaries = {k: used_summary(v, evidence[k], basis, today) for k, v in used_by_model.items()}
    residuals = {}
    for c in cars:
        ev = evidence.get(car_slugs(c, specs_by_car))
        if ev and ev["residual"]:
            residuals[c["id"]] = ev["residual"]

    metrics = {m["id"]: m for m in compute(offers, basis, residuals)}
    for o in offers:
        m = dict(metrics.get(o["id"], {}))
        for k in ("id", "car_id", "finance_type", "status"):
            m.pop(k, None)
        o["metrics"] = m

    # Every sighting of every route, source by source, over time (model/sightings).
    model_of = {c["id"]: "/".join(car_slugs(c, specs_by_car)) for c in cars}
    sightings = series_svc.build(conn, model_of, basis, today, STALE_DAYS)

    by_car: dict[str, list[dict]] = {}
    for o in offers:
        by_car.setdefault(o["car_id"], []).append(o)
    series_by_subject: dict[str, list[dict]] = {}
    for sr in sightings["series"]:
        series_by_subject.setdefault((sr["subject"], sr["route"]), []).append(sr)
    # cars.json is what every page loads, so it carries the card and the table;
    # what only the car page reads (stock by year, spec rows, the cross-check)
    # goes to details.json, fetched on demand.
    details: dict[str, dict] = {}
    for c in cars:
        slugs = car_slugs(c, specs_by_car)
        c["model_key"] = "/".join(slugs)   # the subject of the model's used series
        stock = used_summaries.get(slugs)
        routes = {**sightings["current"].get(c["id"], {}), **sightings["current"].get(f"model:{'/'.join(slugs)}", {})}
        c["deal_summary"] = deal_summary(by_car.get(c["id"], []), metrics, stock, routes)
        c["deal_summary"]["routes"] = _slim_routes(routes)
        c["deal_summary"].pop("true_monthly_by_route", None)   # the app derives it from routes (lib/costs.ts routeCosts)
        c["deal_summary"]["trend"] = trend(series_by_subject.get((c["id"], "cash"), []), today)
        c["picks"] = picks.get(c["id"], [])
        mine = specs_by_car.get(c["id"], [])
        spec_rows = [{"spec_key": sp["spec_key"], "provider": sp["provider"], "variant": sp.get("variant"),
                      "flags": sp.get("flags"), "features": len(sp.get("features") or []), "options": len(sp.get("options") or []),
                      "numbers": sp.get("numbers"), "last_seen_at": sp.get("last_seen_at")} for sp in mine]
        c["spec_count"] = len(mine)
        c["flags"] = car_flags(c, mine)
        c["image"] = car_image(root, c, next((sp for sp in mine if sp.get("image_url")), None)) or fallback_image(c, renders)
        c["used_stock"] = _slim_stock(stock)
        details[c["id"]] = {
            "requirement_check": evaluate_hard(requirements, c),   # the seed's view; the app evaluates its own copy
            "specs": spec_rows,
            # A generated car's fields come from its spec, so there is nothing to cross-check.
            "spec_check": {"rows": [], "disagreements": 0} if c.get("auto") else spec_check(c, mine),
            "used_stock": stock,
        }
        if c.get("auto"):
            c["notes"] = None   # the boilerplate is implied by source_kind

    states: dict[str, int] = {}
    for o in offers:
        s = o["freshness"]["state"] + (" (stale)" if o["freshness"]["stale"] else "")
        states[s] = states.get(s, 0) + 1
    n_obs = conn.execute("SELECT COUNT(*) FROM offer_observations").fetchone()[0]
    unmapped = unmapped_trims(conn)
    n_auto = sum(1 for c in cars if c.get("auto"))
    from pipeline.services.features import FLAGS

    # Per-model tallies for the catalogue page: derivatives (spec rows), cars, cars with a current price.
    by_slug: dict[tuple[str, str], dict] = {}
    for sp in specs:
        k = ((sp.get("make_slug") or sp.get("make") or "").lower(), sp.get("model_slug") or "")
        by_slug.setdefault(k, {"derivatives": 0, "cars": 0, "priced": 0})["derivatives"] += 1
    for c in cars:
        # A hand-curated car has no slugs of its own; its mapped Carwow spec knows them.
        via = next((sp for sp in specs_by_car.get(c["id"], []) if sp.get("model_slug")), {})
        k = ((c.get("make_slug") or via.get("make_slug") or c.get("make") or "").lower(), c.get("model_slug") or via.get("model_slug") or "")
        t = by_slug.setdefault(k, {"derivatives": 0, "cars": 0, "priced": 0})
        t["cars"] += 1
        t["priced"] += int(c["deal_summary"]["current_offers"] > 0 or bool(c["deal_summary"]["routes"]))
    for m in models:
        m.update(by_slug.get((m["make"], m["model"]), {"derivatives": 0, "cars": 0, "priced": 0}))
        m["used"] = sum(1 for l in dedupe_listings(used_by_model.get((m["make"], m["model"]), [])) if l["present"])

    qb = requirements.get("quoting_basis") or {}
    data_page = {
        "generated_at": generated_at,
        "stale_days": STALE_DAYS,
        "assumptions": {k: qb.get(k) for k in ("term_months", "annual_mileage", "savings_rate_apr", "residual_pct_of_list",
                                                 "residual_at_months", "savings_note", "residual_note")},
        "flag_labels": {k: label for k, (label, _) in FLAGS.items()},
        "providers": [
            {"name": p.name, "live": p.live, "description": _provider_blurb(p.name),
             "capabilities": [{"name": c.name, "kinds": list(c.kinds), "parser_version": c.parser_version}
                              for c in p.capabilities.values()]}
            for p in PROVIDERS.values()
        ],
        "runs": latest_runs(conn),
        "unmapped_trims": unmapped,
        "resolution_methods": resolution_methods(conn),
        "offer_states": states,
        "counts": {"cars": len(cars), "cars_curated": len(cars) - n_auto, "cars_generated": n_auto,
                   "offers": len(offers), "observations": n_obs, "specs": len(specs),
                   "specs_mapped": sum(1 for sp in specs if sp.get("car_id")),
                   "trim_map_mapped": conn.execute("SELECT COUNT(*) FROM trim_map WHERE status='mapped'").fetchone()[0],
                   "trim_map_auto": conn.execute("SELECT COUNT(*) FROM trim_map WHERE status='auto'").fetchone()[0],
                   "trim_map_unmapped": len(unmapped),
                   "models": len(models), "makes": len({m["make"] for m in models}),
                   "models_with_deals": sum(1 for m in models if m["has_deals"]),
                   "models_with_specs": sum(1 for m in models if m["has_specs"]),
                   "sightings": sightings["sightings"], "sightings_costed": sightings["costed"], "series": len(sightings["series"]),
                   "used_listings": sum(1 for l in used if l["present"]),
                   "used_models": sum(1 for v in used_by_model.values() if any(l["present"] for l in v)),
                   "models_with_used_residual": sum(1 for e in evidence.values() if e["residual"])},
    }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "counts": {
            "cars": len(cars),
            "cars_generated": n_auto,
            "models": len(models),
            "offers": len(offers),
            "observations": n_obs,
            "cash_benchmarks": sum(1 for o in offers if o["finance_type"] == "cash"),
            "unmapped_trims": len(unmapped),
            "specs": len(specs),
            "used_listings": sum(1 for l in used if l["present"]),
        },
        "runs": latest_runs(conn, 10),
    }
    _write(out / "cars.json", cars)
    _write(out / "details.json", details)
    # ~1,500 spec rows: leave out what the app never reads (the full history keeps it).
    _write(out / "specs.json", [{k: v for k, v in sp.items() if k not in SPEC_PRIVATE} for sp in specs])
    _write(out / "models.json", models)
    _write(out / "used.json", used)
    _write(out / "series.json", sightings["series"])
    _write(out / "residuals.json", sightings["residuals"])
    _write(out / "offers.json", offers)
    _write(out / "requirements.json", requirements, pretty=True)
    _write(out / "data.json", data_page, pretty=True)
    _write(out / "manifest.json", manifest, pretty=True)
    legacy = out / "deals.json"
    if legacy.exists():
        legacy.unlink()
    return manifest
