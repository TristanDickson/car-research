"""Kia UK model specification pages: https://www.kia.com/uk/new-cars/<model>/specification/

Server-rendered HTML tables, each under a `tableTit` heading. Two shapes:
  grade tables   header 'Grade' | 'Air' | 'GT-Line' | ...   rows: feature, ✓ / - per grade
  powertrain     header ''      | 'FWD (58.3 kWh)' | ...     rows: measure, value per powertrain
                 (some rows carry a rowspan group label such as '17" Wheel Air')
plus a POWERTRAINS table that says which grades come with which powertrain.

Emits one 'spec' record per available grade × powertrain: the grade's ticked
features, the powertrain's numbers, and WLTP rows for the grade where the page
breaks them out. Key kia-spec:<model>:<grade>:<powertrain>; car_ref source
'kia-spec' resolved through the trim map.
"""
from __future__ import annotations

import re
from collections.abc import Iterator

from pipeline.providers.http import fetch_url
from pipeline.providers.parse import norm_key, number, slug, text
from pipeline.providers.wayback import backfill_capability, observed_at_for, original_url
from pipeline.providers.types import Capability, Context, Fetched, ParsedRecord, Provider, Target
from pipeline.services.features import flags_for

SITE = "kia-spec"
MODELS = {
    "ev2": "https://www.kia.com/uk/new-cars/ev2/specification/",
    "ev3": "https://www.kia.com/uk/new-cars/ev3/specification/",
    "ev6": "https://www.kia.com/uk/new-cars/ev6/specification/",
    "pv5-passenger": "https://www.kia.com/uk/pbv/specification-pv5-passenger/",
}
TICK = {"✓": True, "✔": True, "●": True, "○": False, "-": False, "–": False, "x": False, "✗": False, "": None}


def url_for(model: str) -> str:
    return MODELS[model]


def discover(target: Target, ctx: Context) -> Iterator[Target]:
    for model in MODELS:
        if target.identifier in ("all", model):
            yield Target(identifier=model, metadata={"model": model, "url": url_for(model)})


def fetch(target: Target, ctx: Context) -> Fetched:
    return fetch_url(target.metadata["url"], ctx)


def _tables(page: str) -> list[dict]:
    """[{title, header: [...], rows: [{group, cells}]}]; a rowspan label in the first
    column is carried onto each row it spans (even when it starts in the header row)."""
    out = []
    for m in re.finditer(r"<table.*?</table>", page, re.S):
        pre = page[max(0, m.start() - 4000): m.start()]
        tits = re.findall(r'class="tableTit"[^>]*>(.*?)</', pre, re.S)
        title = text(tits[-1]).split("Download")[0].strip() if tits else ""
        title = re.sub(r"^(.*?)\s+\1$", r"\1", title)  # some pages print the title twice
        trs = re.findall(r"<tr.*?</tr>", m.group(0), re.S)
        rows, header, group = [], None, None
        for tr in trs:
            cells = re.findall(r"<t([dh])([^>]*)>(.*?)</t[dh]>", tr, re.S)
            vals = [text(c[2]) for c in cells]
            if cells and "rowspan" in cells[0][1]:
                group = vals[0]
                vals = vals[1:]
            if header is None:
                header = vals
                continue
            rows.append({"group": group, "cells": vals})
        out.append({"title": title, "header": header or [], "rows": rows})
    return out


def _meta(label: str) -> dict:
    """What a column / group label says: battery kWh, drive, power, seat counts, trim words.
    'FWD Long Range (71.2kWh) 5 and 7 Seat' → kwh 71.2, fwd, seats {5, 7}
    'Air (61.0 kWh)'                        → kwh 61, trim 'air'
    'AWD Dual Motor 320 BHP'                → awd, bhp 320
    '19" Wheel GT-Line S Heat Pump'         → trim 'gt-line s', heat_pump True
    """
    raw = label.strip().strip("'\"")
    kwh = re.search(r"(\d+(?:\.\d+)?)\s*kwh", raw, re.I)
    bhp = re.search(r"(\d+)\s*bhp", raw, re.I)
    seats = {int(n) for n in re.findall(r"(\d)\s*-?\s*seat", raw, re.I)}
    if re.search(r"\b5\s*(?:and|&|/)\s*7\b", raw):
        seats |= {5, 7}
    trim = re.sub(r"^\s*\d+\"?\s*wheel\s*", "", raw, flags=re.I)
    trim = re.sub(r"\(?\d+(?:\.\d+)?\s*kwh\)?|\d+\s*bhp|dual motor|standard range|long range|\bfwd\b|\bawd\b|\brwd\b|\d\s*-?\s*seat(?:er)?s?( only)?|\b(?:and|&|only|:)\b|\b\d\b|[()-]", " ", trim, flags=re.I)
    trim = re.sub(r"\s+", " ", trim).strip().lower().replace("editon", "edition").replace("gt line", "gt-line")
    heat_pump = "heat pump" in trim
    trim = trim.replace("heat pump", "").strip()
    return {
        "kwh": float(kwh.group(1)) if kwh else None, "bhp": int(bhp.group(1)) if bhp else None,
        "drive": "awd" if re.search(r"\bawd\b|all.wheel|dual motor", raw, re.I) else ("rwd" if re.search(r"\brwd\b", raw, re.I) else "fwd"),
        "seats": seats or None, "trim": trim, "heat_pump": heat_pump, "label": raw,
    }


def _pretty_model(model: str) -> str:
    """'ev3' → 'EV3', 'pv5-passenger' → 'PV5 Passenger'."""
    head, _, tail = model.partition("-")
    return (head.upper() if re.fullmatch(r"[a-z]{2}\d", head) else head.title()) + (f" {tail.replace('-', ' ').title()}" if tail else "")


def _is_tick(v: str) -> bool:
    return v.strip() in ("✓", "✔", "●")


def _is_opt(v: str) -> bool:
    return v.strip().upper() in ("OPT", "O", "OPTION", "OPTIONAL", "○")


def _is_pt_header(header: list[str]) -> bool:
    return any(re.search(r"kwh|bhp|\bfwd\b|\bawd\b|\brwd\b", h, re.I) for h in header[1:])


def _pt_id(c: dict) -> tuple:
    return (c["kwh"], c["drive"], c["bhp"])


def parse_page(page: str, model: str, url: str, observed_at: str) -> list[dict]:
    tables = _tables(page)
    grade_tables = [t for t in tables if t["header"] and not _is_pt_header(t["header"])
                    and t["header"][0].strip().lower() in ("grade", "range", "") and len(t["header"]) > 1
                    and any(_is_tick(c) or _is_opt(c) for r in t["rows"] for c in r["cells"][1:])]
    pt_tables = [t for t in tables if t["header"] and _is_pt_header(t["header"])]
    if not grade_tables:
        return []

    # Equipment per (grade, seats): ✓ standard, OPT option. A column like
    # 'Plus: 5 and 7 Seat' feeds both seat counts; 'Essential 5-Seat' only one.
    std: dict[tuple[str, int | None], list[str]] = {}
    opt: dict[tuple[str, int | None], list[str]] = {}
    grade_order: list[str] = []
    seat_counts: set[int] = set()
    for t in grade_tables:
        cols = [_meta(h) for h in t["header"][1:] if h.strip()]
        for c in cols:
            if c["trim"] and c["trim"] not in grade_order:
                grade_order.append(c["trim"])
            seat_counts |= c["seats"] or set()
        for r in t["rows"]:
            cells = r["cells"]
            if len(cells) < 2:
                continue
            label = cells[0]
            for c, v in zip(cols, cells[1:]):
                v = v.strip()
                for s in (sorted(c["seats"]) if c["seats"] else [None]):
                    key = (c["trim"], s)
                    if _is_tick(v):
                        std.setdefault(key, []).append(label)
                    elif _is_opt(v):
                        opt.setdefault(key, []).append(label)
                    elif v and v not in ("-", "–", "x", "✗") and not v.isdigit():
                        std.setdefault(key, []).append(f"{label} ({v})")

    def kit(trim: str, seats: int | None, table: dict) -> list[str]:
        out = list(table.get((trim, None), []))
        if seats is not None:
            out += table.get((trim, seats), [])
        return list(dict.fromkeys(out))

    # Numbers per column meta, plain and grouped by the rowspan label; availability.
    columns: list[dict] = []
    plain: list[tuple[dict, str, str, str]] = []
    grouped: list[tuple[dict, dict, str, str]] = []
    avail: list[tuple[str, dict]] = []
    insurance: list[tuple[str, dict, str]] = []
    for t in pt_tables:
        cols = [_meta(h) for h in t["header"][1:] if h.strip()]
        for c in cols:
            if _pt_id(c) not in [_pt_id(x) for x in columns]:
                columns.append(c)
        title = t["title"].upper()
        for r in t["rows"]:
            cells = r["cells"]
            if not cells:
                continue
            measure, vals = cells[0], cells[1:]
            if len(vals) == 1 and len(cols) > 1:
                vals = vals * len(cols)
            if title.startswith("POWERTRAIN"):
                g = _meta(measure)["trim"]
                for c, v in zip(cols, vals):
                    if _is_tick(v):
                        avail.append((g, c))
                continue
            for c, v in zip(cols, vals):
                v = v.strip()
                if title.startswith("VEHICLE INSURANCE"):
                    insurance.append((_meta(measure)["trim"], c, v))
                if not v or v in ("-", "–"):
                    continue
                if r["group"]:
                    grouped.append((_meta(r["group"]), c, measure, v))
                else:
                    plain.append((c, t["title"], measure, v))
    if not avail and insurance:
        avail = [(g, c) for g, c, v in insurance if v and v not in ("-", "–", "x")]

    def fits(c: dict, pt: dict, seats: int | None, trim: str | None) -> bool:
        if c["kwh"] is not None and pt["kwh"] is not None and c["kwh"] != pt["kwh"]:
            return False
        if c["bhp"] is not None and pt["bhp"] is not None and c["bhp"] != pt["bhp"]:
            return False
        if c["drive"] != pt["drive"] and (c["kwh"] is not None or c["bhp"] is not None):
            return False
        if seats is not None and c["seats"] and seats not in c["seats"]:
            return False
        if trim is not None and c["trim"] and c["trim"] != trim:
            return False
        return True

    def lookup(pt: dict, seats: int | None, trim: str, heat_pump: bool) -> dict[str, str]:
        out: dict[str, str] = {}
        for c, title, measure, v in plain:
            if fits(c, pt, seats, trim):
                out.setdefault(measure, v)
        for g, c, measure, v in grouped:
            if not fits(c, pt, seats, trim):
                continue
            if g["trim"] and g["trim"] != trim:
                continue
            if g["heat_pump"] != heat_pump:
                continue
            if g["seats"] and seats is not None and seats not in g["seats"]:
                continue
            out[measure] = v
        return out

    def num(d: dict, *names: str) -> float | None:
        for n in names:
            if d.get(n):
                v = re.sub(r"(\d),(\d{3})", r"\1\2", d[n]).replace(" ", "")
                return number(re.split(r"[,/]", v)[0])
        return None

    powertrains = [c for c in columns if c["kwh"] or c["bhp"]] or [{"kwh": None, "bhp": None, "drive": "fwd", "seats": None, "trim": "", "heat_pump": False, "label": ""}]
    # Collapse per-grade columns ('Air (61.0 kWh)', 'GT-Line (61.0 kWh)') into one powertrain each.
    uniq: list[dict] = []
    for c in powertrains:
        if _pt_id(c) not in [_pt_id(x) for x in uniq]:
            uniq.append(c)
    powertrains = uniq
    hp_groups = {(g["trim"], _pt_id(c)) for g, c, _, _ in grouped if g["heat_pump"]}
    model_name = _pretty_model(model)
    rows: list[dict] = []
    seen: set[str] = set()
    for trim in grade_order:
        for pt in powertrains:
            if avail and not any(g == trim and fits(c, pt, None, None) for g, c in avail):
                continue
            if not avail and any(c["trim"] for c in columns) and not any(c["trim"] == trim and _pt_id(c) == _pt_id(pt) for c in columns):
                continue  # per-grade columns say which powertrain each grade has
            for seats in sorted(pt["seats"] or seat_counts or {None}, key=lambda x: (x is None, x)):
                if seats is not None and not any(k in std or k in opt for k in ((trim, seats), (trim, None))):
                    continue
                variants = [(trim, False)]
                if (trim, _pt_id(pt)) in hp_groups:
                    variants.append((trim, True))
                for g, hp in variants:
                    standard = kit(g, seats, std)
                    options = kit(g, seats, opt)
                    if hp:
                        standard = standard + ["Heat Pump"]
                        options = [o for o in options if "heat pump" not in o.lower()]
                    facts = lookup(pt, seats, g, hp)
                    kwh = pt["kwh"] or num(facts, "Battery")
                    trim_label = " ".join(w.upper() if w in ("gt",) else w.capitalize() if w.islower() else w for w in g.replace("gt-line", "GT-Line").split()) + (" Heat Pump" if hp else "")
                    pt_label = " ".join(x for x in (f"{kwh:g} kWh" if kwh else "", pt["drive"].upper(), f"{pt['bhp']} bhp" if pt["bhp"] else "") if x)
                    seat_label = f"{seats}-seat" if seats else ""
                    key = f"{SITE}:{model}:{slug(trim_label)}:{slug(pt_label) or 'all'}" + (f":{seats}seat" if seats else "")
                    if key in seen:
                        continue
                    seen.add(key)
                    rows.append({
                        "spec_key": key, "source": "Kia UK specification", "source_url": url, "observed_at": observed_at,
                        "make": "Kia", "model": model_name, "model_slug": model, "trim": trim_label, "powertrain": pt_label,
                        "seats": seats, "variant": " ".join(x for x in (model_name, trim_label, pt_label, seat_label) if x),
                        "car_ref": {"source": SITE, "key": norm_key("kia", model, trim_label, pt_label, seat_label),
                                    "label": f"Kia {model_name} {trim_label} {pt_label} {seat_label}".strip()},
                        "features": standard, "options": options, "flags": flags_for(standard, options),
                        "numbers": {
                            "battery_kwh": kwh, "drive": pt["drive"].upper(), "seats": seats,
                            "power_kw": num(facts, "Max. Power, kW at rpm", "Max Power (kW)", "Max. Power (kW)"),
                            "power_bhp": pt["bhp"] or num(facts, "Max. Power, bhp at rpm", "Max. power, bhp at rpm", "Max. Power, bhp at rpm (kW)", "Max Power (bhp)"),
                            "kerb_weight_kg": num(facts, "Kerb weight (kg)", "Kerb Weight (kg)"),
                            "boot_l": num(facts, "Luggage compartment capacity, seats upright, litres", "Luggage Compartment Capacity (litres) - Rear seats upright", "Luggage Capacity (litres) - seats up"),
                            "turning_circle_m": num(facts, "Minimum Turning Circle (m)", "Turning Circle (m)", "Minimum turning circle (m)"),
                            "wltp_range_mi": num(facts, "Range (mi) - Combined", "Range (miles) - Combined", "Combined Range (miles)", "Range (mi) - Combined*"),
                            "efficiency_mi_kwh": num(facts, "Electric Energy Consumption (mi/kWh) - Combined"),
                            "zero_to_62_s": num(facts, "Acceleration 0-62 mph (seconds)", "0-62 mph (seconds)", "Acceleration 0-62mph (seconds)"),
                            "top_speed_mph": num(facts, "Maximum Speed (mph)", "Maximum speed (mph)"),
                            "dc_10_80_min": num(facts, "DC Charge Time (10-80%)- 350kW", "DC Charge Time (10-80%) - 350kW", "DC Charge Time (10-80%)- 150kW", "DC Charge Time (10-80%) - 150kW", "DC Charge Time (10-80%) - (350kW)"),
                            "length_mm": num(facts, "Length (mm)"), "width_mm": num(facts, "Width (mm)"), "height_mm": num(facts, "Height (mm)"),
                            "insurance_group": next((v for gi, c, v in insurance if gi == g and fits(c, pt, seats, None) and v not in ("-", "")), None),
                        },
                        "facts": facts,
                    })
    return rows


def parse(body: bytes, target: Target) -> Iterator[ParsedRecord]:
    for row in parse_page(body.decode("utf-8", "replace"), target.metadata["model"], original_url(target), observed_at_for(target)):
        yield ParsedRecord(kind="spec", key=row["spec_key"], row=row)


specs = Capability(name="specs", parser_version="1", discover=discover, fetch=fetch, parse=parse, kinds=("spec",))
provider = Provider(name="kia_specs", default_capability="specs",
                    capabilities={"specs": specs, "backfill": backfill_capability(specs)}, live=True)
