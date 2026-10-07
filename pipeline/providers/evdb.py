"""EV Database (ev-database.org/uk): the measured numbers the manufacturers'
pages leave out, one card per variant on the UK index page.

The index is one large page listing every EV sold in the UK, each card with
the real-world range, efficiency (Wh/mi), kerb weight, 0-62, useable battery,
the average charging power over a 10-80% rapid charge, towing capacity, boot
volume, price, seats, and whether a heat pump and vehicle-to-load are offered.
Variants are EV Database's own ('INSTER Long Range'), not CAP derivatives, so
the rows carry no car id: pipeline/services/facts.py lays them over the
catalogue's cars by model and battery size, with the source recorded per field.

Emits 'spec' records keyed evdb:<id>. One fetch a night; the detail pages are
rate-limited and not read.
"""
from __future__ import annotations

import re
from collections.abc import Iterator

from pipeline.providers.http import fetch_url
from pipeline.providers.parse import money, number, text
from pipeline.providers.types import Capability, Context, Fetched, ParsedRecord, Provider, Target
from pipeline.providers.wayback import observed_at_for

SITE = "evdb"
INDEX = "https://ev-database.org/uk/"
CARD_RE = re.compile(r'<div class="list-item"[^>]*>.*?(?=<div class="list-item"|</section>|$)', re.S)


def discover(target: Target, ctx: Context) -> Iterator[Target]:
    if target.identifier in ("all", "uk"):
        yield Target(identifier="uk", metadata={"url": INDEX})


def fetch(target: Target, ctx: Context) -> Fetched:
    return fetch_url(target.metadata["url"], ctx)


def _hidden(card: str, cls: str) -> str | None:
    m = re.search(rf'class="{re.escape(cls)} hidden">\s*([^<]*?)\s*<', card)
    return m.group(1) if m else None


def _spec(card: str, cls: str) -> str | None:
    m = re.search(rf'class="{re.escape(cls)}">\s*([^<]*?)\s*<', card)
    return m.group(1) if m else None


def _num(s: str | None) -> float | None:
    if s is None or s.strip() in ("", "unknown", "-"):
        return None
    return number(s)


def parse_card(card: str, url: str, observed_at: str) -> dict | None:
    vid = _hidden(card, "id")
    title = re.search(r'<a href="(/uk/car/\d+/[^"]+)" class="title"><span class="[^"]*">(.*?)</span>\s*<span class="model">(.*?)</span>', card, re.S)
    if not vid or not title:
        return None
    make, model = text(title.group(2)), text(title.group(3))
    wh_mi = _num(_spec(card, "efficiency"))
    # The index says only 'available' or 'not available': available is listed (standard or
    # option, the card does not say), not available is a definite none.
    heat = re.search(r'data-tooltip="Heat pump ([^"]*)"', card)
    heat_txt = (heat.group(1) if heat else "").lower()
    heat_pump = None if not heat_txt else "none" if "not" in heat_txt else "standard" if heat_txt.startswith("standard") else "option"
    v2l = re.search(r'data-tooltip="Vehicle-2-Load Bi-directional charging ([^"]*)"', card)
    v2l_ok = bool(v2l) and "not" not in v2l.group(1).lower()
    seats = re.search(r'data-tooltip="Number of seats">.*?<span>(\d+)</span>', card, re.S)
    year_from = _hidden(card, "year_from")
    numbers = {
        "battery_usable_kwh": _num(_hidden(card, "battery")),
        "real_range_mi": _num(_spec(card, "erange_real")),
        "efficiency_mi_kwh": round(1000.0 / wh_mi, 2) if wh_mi else None,
        "efficiency_wh_mi": wh_mi,
        "weight_kg": _num(_hidden(card, "weight")),
        "zero_to_62_s": _num(_hidden(card, "acceleration")),
        "dc_avg_kw": _num(_hidden(card, "fastcharge_speed")),
        "one_stop_range_mi": _num(_spec(card, "long_distance_total")),
        "tow_kg": _num(_hidden(card, "towweight")) or None,
        "boot_l": _num(_spec(card, "cargo")),
        "price_gbp": money(_hidden(card, "pricesort")) or _num(_hidden(card, "pricesort")),
        "seats": int(seats.group(1)) if seats else None,
        "ac_kw": 11.0 if re.search(r'class="obc_11kw hidden">\s*\S', card) else None,
        "year_from": int(year_from) if year_from and year_from.isdigit() else None,
    }
    flags = {"heat_pump": heat_pump, "v2l_any": "standard" if v2l_ok else None, "v2l_external": "standard" if v2l_ok else None}
    shape = re.search(r'class="shape-(\w+) hidden"', card)
    return {
        "spec_key": f"{SITE}:{vid}", "source": "EV Database", "source_url": f"https://ev-database.org{title.group(1)}",
        "observed_at": observed_at, "make": make, "model": model, "trim": model, "variant": f"{make} {model}", "engine": None,
        "cap_id": None, "version_date": f"{year_from}-01-01" if year_from and year_from.isdigit() else None,
        "model_year_hint": year_from if year_from and year_from.isdigit() else None,
        "body": shape.group(1) if shape else None,
        "car_ref": {"source": SITE, "key": vid, "make": make, "model": model, "label": f"{make} {model}"},
        "rrp": numbers["price_gbp"], "carwow_price": None, "image_url": None,
        "features": [], "options": [], "flags": {k: v for k, v in flags.items() if v},
        "numbers": {k: v for k, v in numbers.items() if v is not None},
    }


def parse_page(page: str, url: str, observed_at: str) -> list[dict]:
    rows = []
    seen: set[str] = set()
    for m in CARD_RE.finditer(page):
        r = parse_card(m.group(0), url, observed_at)
        if r and r["spec_key"] not in seen:
            seen.add(r["spec_key"])
            rows.append(r)
    return rows


def parse(body: bytes, target: Target) -> Iterator[ParsedRecord]:
    for row in parse_page(body.decode("utf-8", "replace"), target.metadata["url"], observed_at_for(target)):
        yield ParsedRecord(kind="spec", key=row["spec_key"], row=row)


specs = Capability(name="specs", parser_version="1", discover=discover, fetch=fetch, parse=parse, kinds=("spec",))
provider = Provider(name="evdb", default_capability="specs", capabilities={"specs": specs}, live=True)
