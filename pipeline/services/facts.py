"""Filing EV Database variants under catalogue models, and picking the variant
a car is by its battery. EV Database rows (providers/evdb.py) are variants of a
model, not CAP derivatives: a car takes the row of its model whose useable
battery sits closest to its own gross capacity (useable runs 88-97% of gross).
Everything the variant then says about the car goes through the claim store
(services/claims.py).
"""
from __future__ import annotations

import re

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
