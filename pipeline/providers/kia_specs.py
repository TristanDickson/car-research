"""Kia UK model specification pages: https://www.kia.com/uk/new-cars/<model>/specification/

Server-rendered HTML tables, each under a `tableTit` heading. Two shapes:
  grade tables   header 'Grade' | 'Air' | 'GT-Line' | ...   rows: feature, ✓ / - per grade
  powertrain     header ''      | 'FWD (58.3 kWh)' | ...     rows: measure, value per powertrain
                 (some rows carry a rowspan group label such as '17" Wheel Air'; a value
                 cell with a colspan covers that many columns; the PV5's weight, boot and
                 dimension tables are headed '5-Seat' | '7-Seat' instead)
plus a POWERTRAINS table that says which grades come with which powertrain.

Emits one 'spec' record per available grade × powertrain: the grade's ticked
features, the powertrain's numbers, and WLTP rows for the grade where the page
breaks them out. Key kia-spec:<model>:<grade>:<powertrain>; car_ref source
'kia-spec' resolved through the trim map. Besides `numbers`, a row carries
`charge_times` (every AC and DC charge-time row, with the charger power it is for)
and `notes` (what a number was read from when the cell said more than the number).
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
            if cells and "rowspan" in cells[0][1]:
                group = text(cells[0][2])
                cells = cells[1:]
            vals = []
            for i, (_, attrs, body) in enumerate(cells):
                span = re.search(r'colspan="?(\d+)', attrs) if i else None   # '460l' over two columns is both columns' figure
                vals += [text(body)] * (int(span.group(1)) if span else 1)
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
    '20" Wheel GT-Line S (incl. Heat Pump Versions)' → trim 'gt-line s', heat_pump None (either)
    """
    raw = label.strip().strip("'\"")
    either_hp = bool(re.search(r"incl\.?\s*heat pump", raw, re.I))
    raw = re.sub(r"\(?\s*incl\.?\s*heat pump versions?\s*\)?", " ", raw, flags=re.I).strip()
    kwh = re.search(r"(\d+(?:\.\d+)?)\s*kwh", raw, re.I) or re.search(r"range\W{0,4}(\d{2,3}\.\d)\b", raw, re.I)   # '5-seat Long Range - 71.2'
    bhp = re.search(r"(\d+)\s*bhp", raw, re.I)
    seats = {int(n) for n in re.findall(r"(\d)\s*-?\s*seat", raw, re.I)}
    if re.search(r"\b5\s*(?:and|&|/)\s*7\b", raw):
        seats |= {5, 7}
    trim = re.sub(r"^\s*\d+\"?\s*wheel\s*", "", raw, flags=re.I)
    trim = re.sub(r"\(?\d+(?:\.\d+)?\s*kwh\)?|\d+\s*bhp|dual motor|standard range|long range|\bfwd\b|\bawd\b|\brwd\b|\d\s*-?\s*seat(?:er)?s?( only)?|\b(?:and|&|only)\b|\b\d+\.\d+\b|\b\d\b|[():-]", " ", trim, flags=re.I)   # 'Plus: 5 and 7 Seat' is 'plus'
    trim = re.sub(r"\s+", " ", trim).strip().lower().replace("editon", "edition").replace("gt line", "gt-line")
    heat_pump = None if either_hp else "heat pump" in trim
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


SEAT_ONLY = re.compile(r"\d\s*-?\s*seat(?:er)?s?", re.I)
MILES_PER_KM = 1 / 1.609344


def _is_pt_header(header: list[str]) -> bool:
    """A numbers table: headed by powertrain ('FWD (58.3 kWh)', 'RWD 225 BHP') or only by seat count ('5-Seat')."""
    hs = [h for h in header[1:] if h.strip()]
    return any(re.search(r"kwh|bhp|\bfwd\b|\bawd\b|\brwd\b", h, re.I) for h in hs) or (bool(hs) and all(SEAT_ONLY.fullmatch(h.strip()) for h in hs))


def _pt_id(c: dict) -> tuple:
    return (c["kwh"], c["drive"], c["bhp"])


def _trims(trim: str) -> set[str]:
    """'gt-line / s' → {'gt-line', 'gt-line s'}: a group or column label that names two grades."""
    parts = [p.strip() for p in trim.split("/") if p.strip()]
    if len(parts) < 2:
        return {trim}
    return {parts[0]} | {p if len(p) > 2 else f"{parts[0]} {p}" for p in parts[1:]}


def _qualified(v: str, names: list[str]) -> list[tuple[list[str], str]] | None:
    """'Standard Range: 750kg Long Range: 1,500kg' → [(['standard range'], '750kg'), (['long range'], '1,500kg')];
    'Essential and Plus - 750kg Elite - Cannot Tow - 0kg' → [(['essential', 'plus'], '750kg'), (['elite'], 'Cannot Tow - 0kg')].
    None when the cell does not open with a grade or range name."""
    if not names:
        return None
    alt = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    ms = list(re.finditer(rf"\b((?:{alt})(?:\s*(?:,|\band\b|&|/)\s*(?:{alt}))*)\b\s*[:\-–]\s*", v, re.I))
    if not ms or ms[0].start() != 0:
        return None
    return [([w.lower() for w in re.split(r"\s*(?:,|\band\b|&|/)\s*", m.group(1)) if w],
             v[m.end(): ms[i + 1].start() if i + 1 < len(ms) else len(v)].strip()) for i, m in enumerate(ms)]


def _minutes(v: str) -> float | None:
    """'31m' 31, '1hr 16 mins' 76, '34 hrs 40 mins' 2080, 'Up to 7 hours' 420, '<30 mins' 30;
    None for a cell that prints two times run together ('Up to 5 hours6hrs 30mins')."""
    toks = re.findall(r"(\d+(?:\.\d+)?)\s*(hours?|hrs?|h|minutes|mins?|m)(?![a-z])", v.lower())
    units = [u[0] for _, u in toks]
    if not toks or len(units) != len(set(units)):
        return None
    return sum(float(n) * (60 if u[0] == "h" else 1) for n, u in toks)


def _charge(label: str, v: str) -> dict | None:
    """A charge-time row: 'DC Charge Time (10-80%) - 350kw (max 200A)' | '18 mins'."""
    kind = re.match(r"\s*(ac|dc)\b", label, re.I)
    if not kind or not re.search(r"charg", label, re.I):
        return None
    pct = re.search(r"\(\s*(\d+)\s*-\s*(\d+)\s*%\s*\)", label)
    kw = re.search(r"(\d+(?:\.\d+)?)\s*kwh?\b", label, re.I)   # '50kWh' and '128kWh' in a DC row mean the charger's kW
    return {"kind": kind.group(1).lower(), "from": int(pct.group(1)) if pct else None, "to": int(pct.group(2)) if pct else None,
            "charger_kw": float(kw.group(1)) if kw else None, "minutes": _minutes(v), "printed": v, "label": label}


def _first(v: str | None) -> float | None:
    """The first figure in a cell: '1,885' 1885, '4 060' 4060, '201, 5,200 ~ 9,600' 201, '362/1,201' 362."""
    if not v:
        return None
    v = re.sub(r"(\d),(\d{3})", r"\1\2", v).replace(" ", "")
    return number(re.split(r"[,/]", v)[0])


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
    page_seats = {s for t in grade_tables for h in t["header"][1:] for s in (_meta(h)["seats"] or ())}
    for t in grade_tables:
        cols = [_meta(h) for h in t["header"][1:] if h.strip()]
        used: dict[str, set[int]] = {}
        for c in cols:
            # The PV5 prints 'Plus 5-Seat', 'Plus 5- Seat' where the second is the 7-seat (its ticks are the 7-seat's):
            # a grade's seat count printed twice in one table is the one count of the page it has not had.
            if c["seats"] and len(c["seats"]) == 1:
                had = used.setdefault(c["trim"], set())
                if c["seats"] <= had and len(page_seats - had) == 1:
                    c["seats"] = page_seats - had
                had |= c["seats"]
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
    grouped: list[tuple[dict, dict, str, str, str]] = []
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
                    grouped.append((_meta(r["group"]), c, t["title"], measure, v))
                else:
                    plain.append((c, t["title"], measure, v))
    if not avail and insurance:
        avail = [(g, c) for g, c, v in insurance if v and v not in ("-", "–", "x")]

    # A cell can split by range or grade: 'Standard Range: 1,990 Long Range: 2,070' (the PV5's weights).
    range_kwh: dict[str, float] = {}
    for t in tables:
        for h in t["header"]:
            rn, kw = re.search(r"(standard|long)\s+range", h, re.I), _meta(h)["kwh"]
            if rn and kw:
                range_kwh.setdefault(f"{rn.group(1).lower()} range", kw)
    qualifiers = list(range_kwh) + [t for g in grade_order for t in _trims(g)]

    def resolve(v: str, pt: dict, trim: str) -> str | None:
        parts = _qualified(v, qualifiers)
        if parts is None:
            return v
        for words, val in parts:
            if any(range_kwh.get(w) == pt["kwh"] or w == trim for w in words):
                return val
        return None

    def fits(c: dict, pt: dict, seats: int | None, trim: str | None) -> bool:
        if c["kwh"] is not None and pt["kwh"] is not None and c["kwh"] != pt["kwh"]:
            return False
        if c["bhp"] is not None and pt["bhp"] is not None and c["bhp"] != pt["bhp"]:
            return False
        if c["drive"] != pt["drive"] and (c["kwh"] is not None or c["bhp"] is not None):
            return False
        if seats is not None and c["seats"] and seats not in c["seats"]:
            return False
        if trim is not None and c["trim"] and trim not in _trims(c["trim"]):
            return False
        return True

    def lookup(pt: dict, seats: int | None, trim: str, heat_pump: bool) -> tuple[dict[str, str], dict[str, str]]:
        """The measures that apply to this grade × powertrain × seats, and the table each came from."""
        out: dict[str, str] = {}
        where: dict[str, str] = {}
        for c, title, measure, v in plain:
            if measure not in out and fits(c, pt, seats, trim) and (v := resolve(v, pt, trim)) is not None:
                out[measure], where[measure] = v, title
        # The heat-pump variant takes the plain groups' figures ('GT-Line / S' dimensions) unless a
        # heat-pump group ('19" Wheel GT-Line S Heat Pump') prints its own, which come last and win.
        for g, c, title, measure, v in sorted(grouped, key=lambda x: x[0]["heat_pump"] is True):
            # A group that names the grade ('GT-Line / S') speaks for it whatever the column's own grade.
            if g["trim"] and trim not in _trims(g["trim"]):
                continue
            if not fits(c, pt, seats, None if g["trim"] else trim):
                continue
            if g["heat_pump"] and not heat_pump:
                continue
            if g["seats"] and seats is not None and seats not in g["seats"]:
                continue
            if (v := resolve(v, pt, trim)) is not None:
                out[measure], where[measure] = v, title
        return out, where

    def num(d: dict, *names: str) -> float | None:
        for n in names:
            if d.get(n):
                return _first(d[n])
        return None

    powertrains = [c for c in columns if c["kwh"] or c["bhp"]] or [{"kwh": None, "bhp": None, "drive": "fwd", "seats": None, "trim": "", "heat_pump": False, "label": ""}]
    # Collapse per-grade columns ('Air (61.0 kWh)', 'GT-Line (61.0 kWh)') into one powertrain each.
    uniq: list[dict] = []
    for c in powertrains:
        if _pt_id(c) not in [_pt_id(x) for x in uniq]:
            uniq.append(c)
    powertrains = uniq
    hp_groups = {(g["trim"], _pt_id(c)) for g, c, _, _, _ in grouped if g["heat_pump"]}
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
                    facts, where = lookup(pt, seats, g, hp)
                    measured, charge_times, notes = _numbers(facts, where, standard)
                    insurance_group = next((v for gi, c, v in insurance if gi == g and fits(c, pt, seats, None) and v not in ("-", "")), None)
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
                            "battery_kwh": kwh, "drive": pt["drive"].upper(), "seats": seats, **measured,
                            "power_bhp": pt["bhp"] or measured["power_bhp"],
                            "insurance_group": None if (insurance_group or "").upper() == "TBC" else insurance_group,
                        },
                        "charge_times": charge_times, "notes": notes,
                        "facts": facts,
                    })
    return rows


# Each number and the measure labels it is read from (first match, in page order). The pages word
# one measure several ways: 'Kerb weight (kg)', 'Max Speed (mph)' / 'Maximum Speed (mph)'.
MEASURES = (
    ("power_kw", r"^max\.? power,? kw\b"),
    ("power_bhp", r"^max\.? power,? bhp|^motor output"),
    ("kerb_weight_kg", r"^kerb weight"),
    ("gvwr_kg", r"^gross vehicle weight"),
    ("tow_kg", r"(?<!un)braked trailer weight"),
    ("tow_unbraked_kg", r"unbraked trailer weight"),
    ("tow_ball_kg", r"tow ball weight"),
    ("roof_load_kg", r"roof load"),
    ("boot_l", r"^luggage (?:compartment )?capacity(?!,? front)"),
    ("boot_max_l", r"^max\.? luggage capacity|seats? folded"),
    ("frunk_l", r"^luggage compartment capacity,? front"),
    ("turning_circle_m", r"turning circle"),
    ("wltp_range_mi", r"^range \(mi(?:les)?\).*combined|^combined range \(mi"),
    ("zero_to_62_s", r"0\s*-\s*62\s*mph"),
    ("top_speed_mph", r"^max(?:imum|\.)? speed"),
    ("length_mm", r"^length \(mm\)"),
    ("width_mm", r"^width (?:exc\.? mirrors )?\(mm\)"),
    ("width_mirrors_mm", r"^width with mirrors"),
    ("height_mm", r"^height \(mm\)"),
    ("wheelbase_m", r"^wheelbase"),
)
SOUND_SYSTEM = re.compile(r"premium sound|meridian|harman", re.I)


def _numbers(facts: dict[str, str], where: dict[str, str], features: list[str]) -> tuple[dict, list[dict], dict[str, str]]:
    """The row's numbers from the measures that apply to it; every charge-time row; and a note
    for each number read from a cell that said more than the number."""
    found: dict[str, tuple[str, str]] = {}
    for measure, v in facts.items():
        low = measure.lower()
        for field, rx in MEASURES:
            if field not in found and re.search(rx, low) and "BATTERY" not in where.get(measure, "").upper():
                found[field] = (measure, v)
                break
    out: dict = {field: _first(v) for field, (_, v) in found.items()}
    notes: dict[str, str] = {}

    def figures(v: str) -> list[float]:
        return [float(x) for x in re.findall(r"\d+(?:\.\d+)?", re.sub(r"(\d),(\d{3})", r"\1\2", v))]

    # Power: 'Max. Power, bhp at rpm (kW) | 144 (107.8)' (EV2), 'Motor Output, BHP/kW | 120 / 89.4' (PV5).
    if out.get("power_kw") is None and "power_bhp" in found:
        measure, v = found["power_bhp"]
        f = figures(v)
        if len(f) >= 2 and (re.search(r"bhp\s*/\s*kw", measure, re.I) or re.search(r"\(kw\)", measure, re.I)):
            out["power_kw"] = f[1]
    # Boot: 'seats upright' printed with the folded figure ('362/1,201'); the EV6's 'W/O premium sound / W premium sound'.
    if "boot_l" in found:
        measure, v = found["boot_l"]
        f = figures(v)
        if len(f) == 2 and re.search(r"premium sound", measure, re.I):
            with_sound = any(SOUND_SYSTEM.search(x) for x in features)
            out["boot_l"] = f[1] if with_sound else f[0]
            notes["boot_l"] = f"{v} ({'with' if with_sound else 'without'} the premium sound system): {measure}"
        elif len(f) == 2 and f[1] > f[0] and re.search(r"upright", measure, re.I) and "boot_max_l" not in found:
            out["boot_max_l"] = f[1]
    if "tow_kg" in found and re.search(r"cannot tow", found["tow_kg"][1], re.I):
        out["tow_kg"] = 0.0
        notes["tow_kg"] = found["tow_kg"][1]
    for field in ("kerb_weight_kg", "gvwr_kg"):
        if field in found and len(figures(found[field][1])) > 1:
            notes[field] = found[field][1]   # '2,150 - 2,220', '2050 / 2060' (19" / 20" wheels): the first is kept
    if out.get("wheelbase_m") is not None:
        out["wheelbase_m"] = round(out["wheelbase_m"] / 1000, 3)
    # Efficiency in whichever unit the page prints: mi/kWh (EV3), Wh/km (EV6, PV5), or both ('4.08 (152)', EV2,
    # under a Wh/km label). Values below 20 are mi/kWh, above 50 Wh/km.
    eff = next(((m, v) for m, v in facts.items() if re.search(r"energy consumption.*combined", m, re.I)), None)
    mi = wh = None
    if eff:
        f = figures(eff[1])
        mi = next((x for x in f if 1 <= x < 20), None)
        wh = next((x for x in f if 50 <= x < 1000), None)
        if mi is None and wh:
            mi = round(1000 * MILES_PER_KM / wh, 2)   # mi/kWh = 1000 / (Wh/km × 1.609344)
    out["efficiency_mi_kwh"], out["efficiency_wh_km"] = mi, wh
    charge_times = [c for m, v in facts.items() if (c := _charge(m, v))]
    dc = [c for c in charge_times if c["kind"] == "dc" and (c["from"], c["to"]) == (10, 80) and c["minutes"] is not None]
    fastest = min(dc, key=lambda c: c["minutes"], default=None)
    out["dc_10_80_min"] = fastest["minutes"] if fastest else None
    if fastest and re.search(r"<|up to", fastest["printed"], re.I):
        notes["dc_10_80_min"] = fastest["printed"]
    for field, _ in MEASURES:
        out.setdefault(field, None)
    return out, charge_times, notes


def parse(body: bytes, target: Target) -> Iterator[ParsedRecord]:
    for row in parse_page(body.decode("utf-8", "replace"), target.metadata["model"], original_url(target), observed_at_for(target)):
        yield ParsedRecord(kind="spec", key=row["spec_key"], row=row)


specs = Capability(name="specs", parser_version="2", discover=discover, fetch=fetch, parse=parse, kinds=("spec",))
provider = Provider(name="kia_specs", default_capability="specs",
                    capabilities={"specs": specs, "backfill": backfill_capability(specs)}, live=True)
