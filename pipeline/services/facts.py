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
