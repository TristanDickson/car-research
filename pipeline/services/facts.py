"""Filling a car's facts from the evidence we hold, with the source of every
field recorded.

Two overlays, both pure (cars in, cars out), applied at export:

- EV Database rows (providers/evdb.py) are variants of a model, not CAP
  derivatives. A car takes the row of its model whose useable battery sits
  closest to its own gross capacity (useable runs 88-97% of gross) and fills
  what it lacks: the measured efficiency, 0-62, the average rapid-charge power,
  boot, weight, towing, and a heat pump or vehicle-to-load the card marks.
- A hand-curated car's tri-state fields (heat pump, cabin socket, external
  V2L) describe its trim, so the generated derivatives of the same make, model
  and trim take them where their own spec row said nothing.
- The derivative registry (providers/carwow_model.py) names every derivative
  as CAP does, brackets included. '[No Heat Pump]' says none; a trim that has a
  no-heat-pump version has the heat pump as standard on its other derivatives;
  '[Heat Pump]' and a seat count say what they say; and the trim's description
  on the specification page ('... including a heat pump ...') stands in where
  the name says nothing. The RRP fills a missing list price.

`field_sources` on the car names where each filled field came from; a field
the car already carried is never overwritten.
"""
from __future__ import annotations

import re

FILLABLE_NUMBERS = {
    # evdb number → car field
    "efficiency_mi_kwh": "efficiency_mi_kwh", "zero_to_62_s": "zero_to_62_s", "dc_avg_kw": "dc_avg_kw", "boot_l": "boot_l",
    "weight_kg": "weight_kg", "tow_kg": "tow_kg", "real_range_mi": "real_range_mi", "seats": "seats", "ac_kw": "ac_kw",
}
TRI_FIELDS = ("heat_pump", "internal_v2l", "external_v2l")
USABLE_RATIO = (0.84, 1.0)   # useable / gross, generously


def norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def model_of(make: str, variant_model: str, catalogue: list[dict]) -> dict | None:
    """The catalogue model an EV Database variant belongs to: the longest
    catalogue model name (or slug) that starts the variant's own model text,
    within the make. 'Enyaq Coupe 85' → enyaq-coupe, not enyaq."""
    mk, mo = norm(make), norm(variant_model)
    best = None
    for m in catalogue:
        if norm(m.get("make_name")) != mk and norm(m["make"]) != mk and not (mk == "mercedesbenz" and m["make"] == "mercedes"):
            continue
        for name in (m.get("model_name"), m["model"]):
            k = norm(name)
            if k and mo.startswith(k) and (best is None or len(k) > best[0]):
                best = (len(k), m)
    return best[1] if best else None


def _battery_fit(car_kwh: float | None, usable: float | None) -> float | None:
    """How far a variant's useable battery sits from a car's gross one (0 = ideal); None when it cannot be the same pack."""
    if car_kwh is None or usable is None:
        return None
    ratio = usable / car_kwh
    if not (USABLE_RATIO[0] <= ratio <= USABLE_RATIO[1] + 0.03):
        return None
    return abs(ratio - 0.93)


def pick_variant(car: dict, variants: list[dict]) -> dict | None:
    """The EV Database variant of the car's model that matches its battery; the
    only variant when there is one; else nothing (never a guess)."""
    if not variants:
        return None
    if len(variants) == 1:
        v = variants[0]
        fit = _battery_fit(car.get("battery_kwh"), (v.get("numbers") or {}).get("battery_usable_kwh"))
        return v if fit is not None or car.get("battery_kwh") is None else None
    scored = [(fit, v) for v in variants if (fit := _battery_fit(car.get("battery_kwh"), (v.get("numbers") or {}).get("battery_usable_kwh"))) is not None]
    if not scored:
        return None
    scored.sort(key=lambda fv: fv[0])
    return scored[0][1]


def overlay_evdb(cars: list[dict], evdb_rows: list[dict], catalogue: list[dict]) -> int:
    """Fill each car's missing facts from EV Database. Returns how many fields were filled."""
    by_model: dict[str, list[dict]] = {}
    for r in evdb_rows:
        m = model_of(r.get("make") or "", r.get("model") or "", catalogue)
        if m:
            by_model.setdefault(f"{m['make']}/{m['model']}", []).append(r)
    filled = 0
    for c in cars:
        key = f"{(c.get('make_slug') or '').lower()}/{c.get('model_slug') or ''}"
        v = pick_variant(c, by_model.get(key, []))
        if not v:
            continue
        src = c.setdefault("field_sources", {})
        label = f"EV Database · {v.get('model')}"
        nums = v.get("numbers") or {}
        for ev_key, field in FILLABLE_NUMBERS.items():
            if c.get(field) in (None, "") and nums.get(ev_key) is not None:
                c[field] = nums[ev_key]
                src[field] = label
                filled += 1
        fl = v.get("flags") or {}
        if c.get("heat_pump") in (None, "unknown") and fl.get("heat_pump"):
            c["heat_pump"] = fl["heat_pump"]   # 'option' = offered (the index does not say standard or option), 'none' = not offered
            src["heat_pump"] = label
            filled += 1
        if c.get("external_v2l") in (None, "unknown") and fl.get("v2l_external"):
            c["external_v2l"] = fl["v2l_external"]
            src["external_v2l"] = label
            filled += 1
        c["evdb_url"] = v.get("source_url")
    return filled


NO_HEAT_PUMP = "no heat pump"
HEAT_PUMP_SENTENCE = re.compile(r"[^.]*\bheat pump\b[^.]*", re.I)


def description_says_heat_pump(desc: str | None) -> bool:
    """A trim description that lists the heat pump as fitted, not as an option or an absence."""
    for m in HEAT_PUMP_SENTENCE.finditer(desc or ""):
        sent = m.group(0).lower()
        if not re.search(r"option|no heat pump|without|not (fitted|available|included)|lacks", sent):
            return True
    return False


def overlay_derivatives(cars: list[dict], derivatives: list[dict], descriptions: dict[str, str] | None = None) -> int:
    """What a derivative's CAP name and its trim's twins say, onto the generated
    cars. `descriptions` maps car id → the trim description its spec page printed.
    Returns how many fields were filled."""
    by_cap = {d["cap_id"]: d for d in derivatives}
    twins: dict[tuple, list[dict]] = {}
    for d in derivatives:
        twins.setdefault((d.get("make_slug"), d.get("model_slug"), norm(d.get("trim"))), []).append(d)
    filled = 0
    for c in cars:
        if not c.get("auto"):
            continue
        d = by_cap.get(str(c.get("cap_id") or ""))
        src = c.setdefault("field_sources", {})
        if d:
            low = [b.lower() for b in d.get("brackets") or []]
            label = f"Carwow derivative name · {d['name']}"
            c["cap_name"] = d["name"]
            if c.get("heat_pump") in (None, "unknown"):
                if any(b == NO_HEAT_PUMP for b in low):
                    c["heat_pump"], src["heat_pump"] = "none", label
                    filled += 1
                elif any("heat pump" in b and not b.startswith("no ") for b in low):
                    c["heat_pump"], src["heat_pump"] = "standard", label
                    filled += 1
                elif any(NO_HEAT_PUMP in (b.lower() for b in t.get("brackets") or []) for t in twins.get((d.get("make_slug"), d.get("model_slug"), norm(d.get("trim"))), [])):
                    c["heat_pump"] = "standard"
                    src["heat_pump"] = f"Carwow derivative names · {d['trim']} has a [No Heat Pump] version; this is not it"
                    filled += 1
            for b in d.get("brackets") or []:
                m = re.fullmatch(r"(\d)\s*seats?", b.strip(), re.I)
                if m and c.get("seats") is None:
                    c["seats"], src["seats"] = int(m.group(1)), label
                    filled += 1
            packs = [b for b in d.get("brackets") or [] if not b.lower().startswith("no ") and not re.fullmatch(r"\d\s*seats?", b.strip(), re.I)]
            if packs and set(packs) - set(c.get("packs") or []):
                c["packs"] = sorted(set(c.get("packs") or []) | set(packs))
                src["packs"] = label
                filled += 1
            if c.get("list_price_gbp") in (None, "") and d.get("rrp"):
                c["list_price_gbp"], src["list_price_gbp"] = d["rrp"], label
                filled += 1
        if c.get("heat_pump") in (None, "unknown") and description_says_heat_pump((descriptions or {}).get(c["id"])):
            c["heat_pump"], src["heat_pump"] = "standard", "Carwow trim description"
            filled += 1
    return filled


# Numbers a derivative shares with every other derivative of its model and engine.
ENGINE_FIELDS = ("battery_kwh", "wltp_range_mi", "power_hp", "zero_to_60_s", "top_speed_mph", "efficiency_mi_kwh", "ac_kw",
                 "seats", "doors", "boot_l", "boot_max_l", "turning_circle_m", "wheelbase_m", "drive")


def overlay_engine_twins(cars: list[dict]) -> int:
    """A stub (a derivative only a deals or model page printed) takes the numbers
    of a spec-built derivative of the same make, model and engine: the battery,
    range, power and body are the engine's and the body's, not the trim's.
    Only where every such twin agrees; a field the stub carries is kept."""
    twins: dict[tuple, list[dict]] = {}
    for c in cars:
        if c.get("auto") and c.get("source_kind") == "spec" and c.get("variant"):
            twins.setdefault((norm(c.get("make")), norm(c.get("model")), norm(c.get("variant"))), []).append(c)
    filled = 0
    for g in cars:
        if not (g.get("auto") and g.get("source_kind") == "stub" and g.get("variant")):
            continue
        same = twins.get((norm(g.get("make")), norm(g.get("model")), norm(g.get("variant"))))
        if not same:
            continue
        src = g.setdefault("field_sources", {})
        for field in ENGINE_FIELDS:
            if g.get(field) not in (None, ""):
                continue
            vals = {c.get(field) for c in same if c.get(field) not in (None, "")}
            if len(vals) == 1:
                g[field] = vals.pop()
                src[field] = f"Carwow specification · {same[0]['id']} (same engine)"
                filled += 1
    return filled


def _trim_head(trim: str | None) -> str:
    """The trim's name without its powertrain: '02 · 85kW 49kWh Auto' → '02', 'Ultimate 65kWh' → 'ultimate'."""
    t = (trim or "").split("·")[0]
    words = [w for w in re.split(r"\s+", t.strip()) if w and not re.search(r"\d+\s*kwh|\d+kw\b", w, re.I)]
    return norm(words[0]) if words else ""


def overlay_curated(cars: list[dict]) -> int:
    """A hand-curated car's tri-state fields reach the generated derivatives of
    the same make, model and trim name that said nothing of their own."""
    curated = [c for c in cars if not c.get("auto")]
    filled = 0
    for g in cars:
        if not g.get("auto"):
            continue
        head = _trim_head(g.get("trim"))
        if not head:
            continue
        twins = [c for c in curated if norm(c.get("make")) == norm(g.get("make")) and norm(c.get("model")) == norm(g.get("model"))
                 and _trim_head(c.get("trim")) == head]
        if not twins:
            continue
        src = g.setdefault("field_sources", {})
        for field in TRI_FIELDS:
            if g.get(field) not in (None, "unknown"):
                continue
            vals = {c.get(field) for c in twins if c.get(field) not in (None, "unknown")}
            if len(vals) == 1:
                g[field] = vals.pop()
                src[field] = f"hand-curated · {twins[0]['id']}"
                filled += 1
                if field in (twins[0].get("packs_required") or {}):
                    g.setdefault("packs_required", {})[field] = twins[0]["packs_required"][field]
    return filled
