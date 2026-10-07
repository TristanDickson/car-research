"""Carwow model specification pages: https://www.carwow.co.uk/<make>/<model>/specifications

Server-rendered. One 'trim article' per trim with the standard-equipment list
(every category expanded in the HTML), the trim's RRP and Carwow price, an image
per derivative, and the derivatives available for that trim as CAP ids with a
dated derivative version (the model-year marker). Plus one spec breakdown per
engine (range, acceleration, battery, charging) and model-level facts (seats,
boot, turning circle, wheelbase).

Emits one 'spec' record per CAP derivative: trim equipment + engine numbers +
model facts, keyed carwow-cap:<cap>, resolved to a car through the same
carwow-cap trim map the deals pages use. A derivative nobody curates by hand
becomes a generated car (pipeline/services/autocars.py) so its deals and
history have somewhere to live. Which models to read comes from the catalogue
(carwow_catalog), so every EV on sale is covered.
"""
from __future__ import annotations

import re
from collections.abc import Iterator

from pipeline.providers.carwow_catalog import electric_models, pretty_make
from pipeline.providers.carwow_deals import MODELS
from pipeline.providers.http import fetch_url
from pipeline.providers.parse import money, number, text
from pipeline.providers.wayback import observed_at_for, original_url
from pipeline.providers.types import Capability, Context, Fetched, ParsedRecord, Provider, Target
from pipeline.services.features import flags_for

SITE = "carwow-cap"
HEAD_RE = re.compile(r"class='trim-article__head'")
LINK_RE = re.compile(
    r"data-interaction-derivative='([^']*)'.*?cap_derivative_id=(\d+)&amp;derivative_version_id=car_\d+_(\d{4}-\d{2}-\d{2})", re.S)
ENGINE_RE = re.compile(r"class='specification-breakdown'>(.*?)</header>(.*?)(?=class='specification-breakdown'>|</div>\s*</div>\s*</div>\s*<div class='swiper-slide'|$)", re.S)
PAIR_RE = re.compile(r"specification-breakdown__specification-name'>(.*?)</div>\s*<div class='specification-breakdown__specification-value'>(.*?)</div>", re.S)
DTDD_RE = re.compile(r"<dt[^>]*>(.*?)</dt>\s*<dd[^>]*>(.*?)</dd>", re.S)


def url_for(make: str, model: str) -> str:
    return f"https://www.carwow.co.uk/{make}/{model}/specifications"


def discover(target: Target, ctx: Context) -> Iterator[Target]:
    """Every electric model with a specifications page, from the catalogue; the
    static list when no catalogue has been written yet."""
    models = electric_models(ctx, "has_specs") or [
        {"make": mk, "model": mo, "make_name": pretty_make(mk)} for mk, mo in MODELS]
    for m in models:
        ident = f"{m['make']}/{m['model']}"
        if target.identifier in ("all", ident):
            yield Target(identifier=ident, metadata={"make": m["make"], "model": m["model"], "make_name": m["make_name"],
                                                     "url": url_for(m["make"], m["model"])})


def fetch(target: Target, ctx: Context) -> Fetched:
    return fetch_url(target.metadata["url"], ctx)


def _num(v: str | None, unit: str) -> float | None:
    if not v:
        return None
    v = v.replace(",", "")
    m = re.search(r"(-?\d+(?:\.\d+)?)\s*" + re.escape(unit), v, re.I)
    return float(m.group(1)) if m else None


def _engines(page: str) -> dict[str, dict]:
    """Engine name → numeric facts from its specification breakdown."""
    out: dict[str, dict] = {}
    for m in re.finditer(r"specification-breakdown__title'>\s*(.*?)\s*</div>(.*?)(?=specification-breakdown__title'>|<footer|$)", page, re.S):
        name = text(m.group(1))
        body = m.group(2)
        if name in out:
            continue
        pairs = {text(k): text(v) for k, v in PAIR_RE.findall(body)}
        cats = [text(c) for c in re.findall(r"specification-breakdown__category-list-item'>\s*(.*?)\s*</li>", body, re.S)]
        out[name] = {
            "engine": name, "fuel": cats[0] if cats else None,
            "power_bhp": next((number(c) for c in cats if "bhp" in c), None),
            "drive": next((c for c in cats if "wheel drive" in c.lower()), None),
            "zero_to_60_s": _num(pairs.get("Acceleration (0-60mph)") or pairs.get("Acceleration (0-62mph)"), "s"),
            "wltp_range_mi": _num(pairs.get("Battery range"), "miles"),
            "battery_kwh": _num(pairs.get("Battery capacity"), "kWh"),
            "efficiency_mi_kwh": _num(pairs.get("Consumption"), "miles/kWh"),
            "top_speed_mph": _num(pairs.get("Top speed"), "mph"),
            "first_year_tax_gbp": money(pairs.get("First year road tax")),
            "raw": pairs,
        }
    return out


def parse_page(page: str, make: str, model: str, url: str, observed_at: str, make_name: str | None = None) -> list[dict]:
    make_name = make_name or pretty_make(make)
    facts = {text(k): text(v) for k, v in DTDD_RE.findall(page)}
    model_facts = {
        "seats": int(number(facts.get("Number of seats")) or 0) or None,
        "doors": int(number(facts.get("Number of doors")) or 0) or None,
        "boot_l": _num(facts.get("Boot (seats up)"), "L"),
        "boot_max_l": _num(facts.get("Boot (seats down)"), "L"),
        "turning_circle_m": _num(facts.get("Turning circle"), "m"),
        "wheelbase_m": _num(facts.get("Wheelbase"), "m"),
        "battery_kwh": _num(facts.get("Battery capacity"), "kWh"),
        "used_from_gbp": money(facts.get("Used")),
    }
    engines = _engines(page)
    heads = [m.start() for m in HEAD_RE.finditer(page)]
    rows: list[dict] = []
    seen: set[str] = set()
    for i, p in enumerate(heads):
        block = page[p:heads[i + 1] if i + 1 < len(heads) else len(page)]
        t1 = re.search(r"trim-article__title-part-1'>(.*?)</span>", block, re.S)
        t2 = re.search(r"trim-article__title-part-2'>(.*?)</span>", block, re.S)
        model_name, trim = (text(t1.group(1)) if t1 else model), (text(t2.group(1)) if t2 else "")
        rrp = money((re.search(r"trim-article__rrp'>(.*?)</", block, re.S) or [None, None])[1])
        price = money((re.search(r"trim-article__carwow-price'>(.*?)</", block, re.S) or [None, None])[1])
        desc = re.search(r"trim-article__description'>(.*?)</div>", block, re.S)
        eq = re.search(r"trim-article__standard-equipment'>(.*)", block, re.S)
        items = [text(x) for x in re.findall(r"<li>(.*?)</li>", eq.group(1), re.S)] if eq else []
        items = [x for x in dict.fromkeys(items) if x]
        img = re.search(r"trim-article__image'>\s*<img[^>]*src=\"([^\"]+)\"", block, re.S)
        for engine, cap, version in LINK_RE.findall(block):
            if cap in seen:
                continue
            seen.add(cap)
            e = dict(engines.get(engine, {}))
            # Engine facts win over model facts, but never with a blank; the battery
            # is usually only printed in the engine name ('108kW 42kWh Auto').
            numbers = dict(model_facts)
            numbers.update({k: v for k, v in e.items() if k != "raw" and v is not None})
            numbers["battery_kwh"] = e.get("battery_kwh") or _num(engine, "kWh") or model_facts.get("battery_kwh")
            ac = next((_num(it, "kW") for it in items if re.search(r"\bAC\b.*charger|on-?board charger", it, re.I)), None)
            if ac:
                numbers["ac_kw"] = ac
            rows.append({
                "spec_key": f"{SITE}:{cap}", "source": "Carwow specifications", "source_url": url,
                "observed_at": observed_at, "make": make_name, "make_slug": make, "model": model_name, "model_slug": model,
                "trim": trim, "variant": f"{model_name} {trim} {engine}".strip(), "engine": engine, "cap_id": cap,
                "version_date": version, "model_year_hint": version[:4],
                "car_ref": {"source": SITE, "key": cap, "label": f"{make_name} {model_name} {engine} · {trim} · RRP £{rrp:,.0f}" if rrp else f"{make_name} {model_name} {engine} · {trim}"},
                "rrp": rrp, "carwow_price": price,
                "image_url": img.group(1).replace("&amp;", "&").replace("filter%5Bsize%5D=400", "filter%5Bsize%5D=800") if img else
                             f"https://car-data.carwow.co.uk/image?filter%5Bangle%5D=22&filter%5Bcolour%5D=black&filter%5Bderivative_id%5D={cap}&filter%5Bsize%5D=800",
                "description": text(desc.group(1)) if desc else None,
                "features": items, "options": [], "flags": flags_for(items, []),
                "numbers": numbers,
                "raw_numbers": e.get("raw", {}),
            })
    return rows


def parse(body: bytes, target: Target) -> Iterator[ParsedRecord]:
    for row in parse_page(body.decode("utf-8", "replace"), target.metadata["make"], target.metadata["model"],
                          original_url(target), observed_at_for(target), target.metadata.get("make_name")):
        yield ParsedRecord(kind="spec", key=row["spec_key"], row=row)


# No Wayback backfill here: a spec row is the current state of a derivative,
# and an older capture must not overwrite it.
specs = Capability(name="specs", parser_version="2", discover=discover, fetch=fetch, parse=parse, kinds=("spec",))
provider = Provider(name="carwow_specs", default_capability="specs", capabilities={"specs": specs}, live=True)
