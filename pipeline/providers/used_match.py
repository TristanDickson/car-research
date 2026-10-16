"""Filing a retailer's used listing under a catalogue model, by name.

Retailers name the model (cinch: 'Kona', 'ID.4'; Motorpoint: 'IONIQ 5'), the
catalogue names it as Carwow does ('Kona Electric', 'ID.4', 'Ioniq 5'). The
match is on letters and digits only, accents folded (pipeline/normalise.py),
exact first, then with the catalogue's electric suffix dropped ('Kona Electric'
→ 'kona'), then the alias table for the handful the retailers file differently
(BMW 'i4 Gran Coupe' is the i4; normalise.MODEL_ALIASES).
"""
from __future__ import annotations

import re

from pipeline.normalise import MAKE_ALIASES, MODEL_ALIASES, compact

# What a catalogue model name carries that a retailer's leaves out.
ELECTRIC_SUFFIXES = ("electric", "recharge", "etense", "etech", "ev", "e")


def norm(s: str | None) -> str:
    return compact(s)


def bare(s: str | None) -> str:
    """The model name without its electric marker: 'Kona Electric' → 'kona',
    '500e' → '500', 'e-2008' → '2008', 'e-Berlingo' → 'berlingo'."""
    k = norm(re.sub(r"^e[- ](?=\w)", "", s or "", flags=re.I))
    for suf in ELECTRIC_SUFFIXES:
        if k.endswith(suf) and len(k) > len(suf):
            return k[: -len(suf)]
    return k


def make_slugs(make: str, models: list[dict]) -> set[str]:
    """The catalogue make slug(s) a retailer's make name can mean."""
    k = norm(make)
    slugs = {m["make"] for m in models if norm(m.get("make_name")) == k or norm(m["make"]) == k}
    if k in MAKE_ALIASES:
        slugs.add(MAKE_ALIASES[k])
    return slugs


def match_model(make: str, model: str, models: list[dict]) -> dict | None:
    """The catalogue model (a dict with make, model, make_name, model_name) a
    retailer's (make, model) names, or None when we do not sell it."""
    makes = make_slugs(make, models)
    pool = [m for m in models if m["make"] in makes]
    mo = norm(model)
    exact = [m for m in pool if mo in (norm(m.get("model_name")), norm(m["model"]))]
    if exact and len({m["model"] for m in exact}) == 1:
        return exact[0]
    loose = [m for m in pool if mo in (bare(m.get("model_name")), bare(m["model"]))]
    if loose and len({m["model"] for m in loose}) == 1:
        return loose[0]
    for mk in makes:
        alias = MODEL_ALIASES.get((mk, mo))
        if alias:
            return next((m for m in pool if m["make"] == mk and m["model"] == alias), None)
    return None
