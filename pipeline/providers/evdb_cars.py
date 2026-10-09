"""EV Database car pages (ev-database.org/uk/car/<id>/<name>): everything the index
card leaves out, per variant.

The index (providers/evdb.py) gives each variant's real range, efficiency, 0-62,
useable battery and average rapid-charge power. The car page adds what a buyer
compares on: length, width (with and without mirrors), height and wheelbase; weights,
payload, roof load and towing; top speed, power and torque; the AC rate, the DC peak,
the 10-80% time on the fastest charger; the V2L outlets inside and out and their power;
whether the heat pump is standard; ISOFIX seats; the Euro NCAP scores; the WLTP range;
the real range in cold and mild weather; and whether the variant is still on sale.

The site rate-limits hard, so discover only lists the pages of variants filed under a
catalogue model, stalest first, and skips any read within the last fortnight; fetch
paces itself well beyond the runner's default. Emits 'spec' records keyed
evdb-car:<id>; services/claims.py lays them over the index row of the same id.
"""
from __future__ import annotations

import html as H
import json
import re
import sqlite3
import time
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

from pipeline.providers.http import fetch_url
from pipeline.providers.parse import money, text
from pipeline.providers.types import Capability, Context, Fetched, ParsedRecord, Provider, Target
from pipeline.providers.wayback import observed_at_for

SITE = "evdb-car"
FRESH_DAYS = 14
PACE_SECONDS = 25.0   # between car pages; the site answers 429 to anything quicker for long
TOKEN_RE = re.compile(r"<h2[^>]*>(.*?)</h2>|<h3[^>]*>(.*?)</h3>|<tr>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>\s*</tr>", re.S)
FAST_RE = re.compile(r'<table class="charging-table-fast">(.*?)</table>', re.S)
CELLS_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
NUM_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", " ", s))).replace("†", "").strip()


def _n(s: str | None) -> float | None:
    if not s or s.strip() in ("-", "No Data", "N/A"):
        return None
    m = NUM_RE.search(s)
    return float(m.group(0).replace(",", "")) if m else None


def _section(h2: str) -> str:
    t = _clean(h2)
    for key in ("Price", "Lease", "Real Range", "Long Distance", "Battery", "Charging", "Performance", "Bidirectional",
                "Energy Consumption", "Real Energy", "Safety", "Dimensions", "Miscellaneous", "Company Car", "Home and Destination",
                "Rapid Charging"):
        if t.startswith(key):
            return key
    return t


def parse_tables(page: str) -> dict[str, str]:
    """Every labelled value on the page as 'Section › Subsection › Label' → text; a label seen twice in a
    section (the AC and the DC 'Charge Port') gets ' #2'."""
    out: dict[str, str] = {}
    section, sub = "", ""
    for m in TOKEN_RE.finditer(page):
        if m.group(1) is not None:
            section, sub = _section(m.group(1)), ""
            if section == "Price":
                out["Price › from"] = _clean(m.group(1)).replace("Price from", "").strip()
        elif m.group(2) is not None:
            sub = _clean(m.group(2))
        else:
            label = _clean(m.group(3)).rstrip("*").strip()
            if not label or label[0].isdigit():
                continue
            key = " › ".join(x for x in (section, sub, label) if x)
            if key in out:
                key += " #2"
            if key in out:
                continue
            value = m.group(4)
            stars = len(re.findall(r'class="fas fa-star"', value))
            out[key] = str(stars) if stars and not _clean(value) else _clean(value)
    return out


def rapid_rows(page: str) -> list[list[str]]:
    """The 10-80% table: [charger, max power, average power, time, rate] per charger, slowest first."""
    m = FAST_RE.search(page)
    if not m:
        return []
    rows = []
    for tr in re.findall(r"<tr>(.*?)</tr>", m.group(1), re.S):
        cells = [_clean(c) for c in CELLS_RE.findall(tr)]
        if len(cells) == 5:
            rows.append(cells)
    return rows


def _yes(v: str | None) -> bool | None:
    if v is None or v in ("No Data", ""):
        return None
    return v.lower().startswith("yes")


def _first(t: dict[str, str], *keys: str) -> str | None:
    for k in keys:
        if t.get(k) not in (None, "", "No Data", "-"):
            return t[k]
    return None


def numbers_of(t: dict[str, str], rapid: list[list[str]]) -> dict:
    """The page's values under the field names the car records use."""
    power = _first(t, "Performance › Total Power")
    drive = (_first(t, "Performance › Drive") or "").lower()
    since = _first(t, "Price › Available to order since")
    until = _first(t, "Price › Available to order until")
    out = {
        "battery_kwh": _n(_first(t, "Battery › Nominal Capacity")),
        "battery_usable_kwh": _n(_first(t, "Battery › Useable Capacity")),
        "architecture_v": _n(_first(t, "Battery › Architecture")),
        "battery_chemistry": _first(t, "Battery › Cathode Material"),
        "warranty_years": _n(_first(t, "Battery › Warranty Period")),
        "warranty_miles": _n(_first(t, "Battery › Warranty Mileage")),
        "ac_kw": _n(_first(t, "Charging › Home / Destination › Charge Power", "Charging › Charge Power")),
        "dc_peak_kw": _n(_first(t, "Charging › Rapid Charging › Charge Power (max)", "Charging › Charge Power (max)")),
        "dc_avg_kw": _n(_first(t, "Charging › Rapid Charging › Charge Power (10-80%)", "Charging › Charge Power (10-80%)")),
        "dc_10_80_min": _n(rapid[-1][3]) if rapid else None,
        "charge_port": _first(t, "Charging › Rapid Charging › Port Location", "Charging › Home / Destination › Port Location"),
        "zero_to_62_s": _n(_first(t, "Performance › Acceleration 0 - 62 mph")),
        "top_speed_mph": _n(_first(t, "Performance › Top Speed")),
        "power_kw": _n(power),
        "power_hp": _n(re.search(r"\((\d[\d,]*)\s*hp\)", power).group(1)) if power and re.search(r"\((\d[\d,]*)\s*hp\)", power) else None,
        "torque_lbft": _n(_first(t, "Performance › Total Torque")),
        "drive": "AWD" if "all" in drive or "awd" in drive or "4" in drive else "RWD" if "rear" in drive else "FWD" if "front" in drive else None,
        "v2l_kw": _n(_first(t, "Bidirectional › Vehicle-to-Load (V2L) › Max. Output Power")),
        "wltp_range_mi": _n(_first(t, "Energy Consumption › WLTP Ratings (TEL) › Range", "Energy Consumption › WLTP Ratings › Range")),
        "wltp_range_max_trim_mi": _n(_first(t, "Energy Consumption › WLTP Ratings (TEH) › Range")),
        "real_range_mi": _n(_first(t, "Energy Consumption › EVDB Real Range › Range")),
        "real_range_cold_mi": _n(_first(t, "Real Range › Combined - Cold Weather")),
        "real_range_mild_mi": _n(_first(t, "Real Range › Combined - Mild Weather")),
        "motorway_range_cold_mi": _n(_first(t, "Real Range › Highway - Cold Weather")),
        "motorway_range_mild_mi": _n(_first(t, "Real Range › Highway - Mild Weather")),
        "ncap_stars": _n(_first(t, "Safety › Safety Rating")),
        "ncap_adult_pct": _n(_first(t, "Safety › Adult Occupant")),
        "ncap_child_pct": _n(_first(t, "Safety › Child Occupant")),
        "ncap_vru_pct": _n(_first(t, "Safety › Vulnerable Road Users")),
        "ncap_assist_pct": _n(_first(t, "Safety › Safety Assist")),
        "ncap_year": _n(_first(t, "Safety › Rating Year")),
        "length_mm": _n(_first(t, "Dimensions › Length")),
        "width_mm": _n(_first(t, "Dimensions › Width")),
        "width_mirrors_mm": _n(_first(t, "Dimensions › Width with mirrors")),
        "height_mm": _n(_first(t, "Dimensions › Height")),
        "wheelbase_m": (_n(_first(t, "Dimensions › Wheelbase")) or 0) / 1000 or None,
        "weight_kg": _n(_first(t, "Dimensions › Weight Unladen (EU)")),
        "gvwr_kg": _n(_first(t, "Dimensions › Gross Vehicle Weight (GVWR)")),
        "payload_kg": _n(_first(t, "Dimensions › Max. Payload")),
        "boot_l": _n(_first(t, "Dimensions › Cargo Volume")),
        "boot_max_l": _n(_first(t, "Dimensions › Cargo Volume Max")),
        "frunk_l": _n(_first(t, "Dimensions › Cargo Volume Frunk")),
        "roof_load_kg": _n(_first(t, "Dimensions › Roof Load")),
        "tow_kg": _n(_first(t, "Dimensions › Towing Weight Braked")),
        "tow_unbraked_kg": _n(_first(t, "Dimensions › Towing Weight Unbraked")),
        "seats": _n(_first(t, "Miscellaneous › Seats")),
        "isofix_seats": _n(_first(t, "Miscellaneous › Isofix")) if _yes(_first(t, "Miscellaneous › Isofix")) else (0 if _yes(_first(t, "Miscellaneous › Isofix")) is False else None),
        "turning_circle_m": _n(_first(t, "Miscellaneous › Turning Circle")),
        "platform": _first(t, "Miscellaneous › Platform"),
        "segment": _first(t, "Miscellaneous › Segment"),
        "body": (_first(t, "Miscellaneous › Car Body") or "").lower() or None,
        "roof_rails": _yes(_first(t, "Miscellaneous › Roof Rails")),
        "on_sale": None if not _first(t, "Price › Availability") else "available" in _first(t, "Price › Availability").lower() and "not" not in _first(t, "Price › Availability").lower(),
        "on_sale_since": _month(since),
        "on_sale_until": _month(until),
        "price_gbp": money(_first(t, "Price › from")),
        "insurance_group": next((v for v in (_first(t, "Lease › Insurance Group", "Price › Insurance Group"),) if v and v != "N/A"), None),
    }
    if out.get("seats") is not None:
        out["seats"] = int(out["seats"])
    for k in ("isofix_seats", "ncap_stars", "ncap_year", "architecture_v", "warranty_years"):
        if isinstance(out.get(k), float):
            out[k] = int(out[k])
    return {k: v for k, v in out.items() if v not in (None, "")}


def _month(s: str | None) -> str | None:
    """'October 2024' → '2024-10'."""
    if not s:
        return None
    try:
        return datetime.strptime(s.strip(), "%B %Y").strftime("%Y-%m")
    except ValueError:
        return None


def flags_of(t: dict[str, str]) -> dict[str, str]:
    """Heat pump (standard or an option), the cabin socket and the exterior adapter, read from the page."""
    out: dict[str, str] = {}
    hp, hp_std = _yes(_first(t, "Miscellaneous › Heat pump (HP)")), _first(t, "Miscellaneous › HP Standard Equipment")
    if hp is True:
        out["heat_pump"] = "standard" if (hp_std or "").lower().startswith("yes") else "option"
    elif hp is False:
        out["heat_pump"] = "none"
    v2l = _yes(_first(t, "Bidirectional › Vehicle-to-Load (V2L) › V2L Supported"))
    inside = t.get("Bidirectional › Vehicle-to-Load (V2L) › Interior Outlet(s)")
    outside = t.get("Bidirectional › Vehicle-to-Load (V2L) › Exterior Outlet(s)")
    if v2l is False:
        out.update({"v2l_any": "none", "v2l_internal": "none", "v2l_external": "none", "three_pin_socket": "none"})
    elif v2l:
        out["v2l_any"] = "standard"
        if inside and inside not in ("No Data",):
            out["v2l_internal"] = "none" if inside == "-" else "standard"
            if re.search(r"UK Socket|BS ?1363|3.pin", inside, re.I):
                out["three_pin_socket"] = "standard"
        if outside and outside not in ("No Data",):
            out["v2l_external"] = "none" if outside == "-" else "standard"
    return out


def parse_page(page: str, meta: dict, observed_at: str) -> dict | None:
    t = parse_tables(page)
    if not t:
        return None
    numbers = numbers_of(t, rapid_rows(page))
    vid = meta["evdb_id"]
    return {
        "spec_key": f"{SITE}:{vid}", "source": "EV Database", "source_url": meta["url"], "observed_at": observed_at,
        "evdb_id": vid, "make": meta.get("make"), "model": meta.get("model"), "trim": meta.get("model"),
        "variant": f"{meta.get('make')} {meta.get('model')}", "engine": None, "cap_id": None, "version_date": None,
        "car_ref": {"source": SITE, "key": vid, "make": meta.get("make"), "model": meta.get("model"), "label": f"{meta.get('make')} {meta.get('model')}"},
        "rrp": numbers.get("price_gbp"), "carwow_price": None, "image_url": None, "features": [], "options": [],
        "flags": flags_of(t), "numbers": numbers,
        "facts": {k: v for k, v in t.items() if not k.startswith(("Company Car", "Real Energy", "Home and Destination", "Long Distance"))},
    }


# ---------------------------------------------------------------- the run

PER_RUN = 60   # car pages per run (25 minutes at the pace): the nightly scrape keeps filling and refreshing, a batch at a time
BUDGET_SECONDS = 25 * 60   # and never more than this of the nightly job, however slow the site is tonight


def discover(target: Target, ctx: Context) -> Iterator[Target]:
    """Car pages of EV Database variants filed under a catalogue model. Never-read pages first, one per
    model in turn (the newest variant of every model, then the next newest, ...), so each model gets its
    body numbers early; then pages last read more than FRESH_DAYS ago, stalest first. PER_RUN a run."""
    global _refused
    conn: sqlite3.Connection | None = ctx.extras.get("db")
    if conn is None:
        return
    if ctx.extras.get("reparse"):   # a parser change: every page read so far, from the stored bodies
        for (vid,) in conn.execute("SELECT DISTINCT target FROM artifacts WHERE source='evdb_cars'"):
            if target.identifier in ("all", vid):
                p = conn.execute("SELECT payload FROM specs WHERE spec_key=?", (f"evdb:{vid}",)).fetchone()
                meta = json.loads(p["payload"]) if p else {}
                yield Target(identifier=vid, metadata={"evdb_id": vid, "url": meta.get("source_url"), "make": meta.get("make"), "model": meta.get("model")})
        return
    from pipeline.services.facts import model_of, norm
    try:
        catalogue = [dict(r) for r in conn.execute("SELECT slug, make, model, make_name, model_name FROM models WHERE electric=1")]
        rows = conn.execute("SELECT spec_key, payload FROM specs WHERE source='evdb'").fetchall()
        seen = {r["spec_key"].split(":", 1)[1]: r["last_seen_at"] for r in conn.execute("SELECT spec_key, last_seen_at FROM specs WHERE source='evdb_cars'")}
    except sqlite3.OperationalError:
        return
    cutoff = (datetime.now(timezone.utc) - timedelta(days=FRESH_DAYS)).isoformat()
    fresh: dict[str, list[tuple[int, str, dict]]] = {}
    stale: list[tuple[str, str, dict]] = []
    for r in rows:
        p = json.loads(r["payload"])
        vid = r["spec_key"].split(":", 1)[1]
        if target.identifier not in ("all", vid):
            continue
        m = model_of(p.get("make") or "", p.get("model") or "", catalogue)
        if not m:
            continue
        last = seen.get(vid)
        if last is None or target.identifier != "all":
            fresh.setdefault(m["slug"], []).append((-(p.get("numbers") or {}).get("year_from", 0), vid, p))
        elif last < cutoff:
            stale.append((last, vid, p))
    # The models the household has hand-curated cars for go first.
    try:
        curated = {(norm(r[0]), norm(r[1])) for r in conn.execute(
            "SELECT json_extract(payload, '$.make'), json_extract(payload, '$.model') FROM cars WHERE COALESCE(json_extract(payload, '$.auto'), 0) = 0")}
    except sqlite3.OperationalError:
        curated = set()
    by_slug = {m["slug"]: m for m in catalogue}
    first = lambda slug: 0 if (norm(by_slug[slug].get("make_name") or by_slug[slug]["make"]), norm(by_slug[slug].get("model_name") or by_slug[slug]["model"])) in curated else 1
    queues = [sorted(v) for _, v in sorted(fresh.items(), key=lambda kv: (first(kv[0]), kv[0]))]
    order: list[tuple[str, dict]] = []
    while any(queues):
        for q in queues:
            if q:
                _, vid, p = q.pop(0)
                order.append((vid, p))
    order += [(vid, p) for _, vid, p in sorted(stale)]
    budget = int(ctx.extras.get("evdb_cars_per_run", PER_RUN)) if target.identifier == "all" else len(order)
    deadline = time.monotonic() + float(ctx.extras.get("evdb_cars_budget_s", BUDGET_SECONDS))
    _refused = False
    for vid, p in order[:budget]:
        # Fetching is lazy (the runner fetches each target as it is yielded), so this stops the run.
        if time.monotonic() > deadline or _refused:
            return
        yield Target(identifier=vid, metadata={"evdb_id": vid, "url": p["source_url"], "make": p.get("make"), "model": p.get("model")})


_last_fetch = 0.0
_pace = PACE_SECONDS
_refused = False   # a 429 outlasted the cooldown: the rest of the run would be refused too
COOLDOWN_SECONDS = 240.0


def fetch(target: Target, ctx: Context) -> Fetched:
    """One car page, paced; a 429 slows every later fetch and waits out the site's window once before giving up."""
    global _last_fetch, _pace, _refused
    for attempt in range(2):
        wait = _last_fetch + max(_pace, ctx.delay_seconds) - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        try:
            return fetch_url(target.metadata["url"], ctx, retries=0)
        except Exception as e:  # noqa: BLE001
            if "429" not in str(e) or attempt:
                _refused = _refused or "429" in str(e)
                raise
            _pace = min(_pace + 15.0, 120.0)
            time.sleep(COOLDOWN_SECONDS)
        finally:
            _last_fetch = time.monotonic()
    raise RuntimeError("unreachable")


def parse(body: bytes, target: Target) -> Iterator[ParsedRecord]:
    row = parse_page(body.decode("utf-8", "replace"), target.metadata, observed_at_for(target))
    if row:
        yield ParsedRecord(kind="spec", key=row["spec_key"], row=row)


cars = Capability(name="cars", parser_version="1", discover=discover, fetch=fetch, parse=parse, kinds=("spec",))
provider = Provider(name="evdb_cars", default_capability="cars", capabilities={"cars": cars}, live=True)
