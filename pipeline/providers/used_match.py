"""Filing a retailer's used listing under a catalogue model, by name.

Retailers name the model (cinch: 'Kona', 'ID.4'; Motorpoint: 'IONIQ 5'), the
catalogue names it as Carwow does ('Kona Electric', 'ID.4', 'Ioniq 5'). The
match is on letters and digits only, exact first, then with the catalogue's
electric suffix dropped ('Kona Electric' → 'kona'), then an alias table for
the handful the retailers file differently (BMW 'i4 Gran Coupe' is the i4).
Only aliases that are the same car: cinch's 'e-Niro' is the previous
generation, not the Niro EV, and stays unmatched.
"""
from __future__ import annotations

import re

# Retailer make names, normalised, whose catalogue make slug is spelt differently.
MAKE_ALIASES = {"mercedesbenz": "mercedes", "ssangyong": "kgm-motors", "kgm": "kgm-motors", "ora": "gwm", "gwmora": "gwm",
                "mgmotoruk": "mg"}
# (catalogue make slug, retailer model name normalised) → catalogue model slug.
MODEL_ALIASES = {
    ("audi", "a6"): "a6-sportback-e-tron", ("audi", "a6avant"): "a6-avant-e-tron", ("audi", "q6"): "q6-e-tron",
    ("audi", "q4etronsportback"): "q4-e-tron-sportback", ("audi", "q4"): "q4-e-tron", ("audi", "q8"): "q8-e-tron",
    ("bmw", "i4grancoupe"): "i4",
    ("ds", "ds3crossback"): "3-crossback-e-tense",
    ("gwm", "funkycat"): "ora-03", ("gwm", "ora03"): "ora-03",
    ("honda", "hondae"): "e",
    ("kgm-motors", "korandoemotion"): "korando-e-motion",
    ("lexus", "ux"): "ux-300e",
    ("omoda", "5"): "omoda-e5",
    ("polestar", "4coupe"): "4",
    ("skoda", "enyaqiv"): "enyaq", ("skoda", "citigo"): "citigo-e-iv",
    ("smart", "forfour"): "eq-forfour",
    ("volkswagen", "golf"): "e-golf",
}
# What a catalogue model name carries that a retailer's leaves out.
ELECTRIC_SUFFIXES = ("electric", "recharge", "etech", "ev", "e")


def norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def bare(s: str | None) -> str:
    """The model name without its electric marker: 'Kona Electric' → 'kona',
    '500e' → '500', 'e-2008' → '2008', 'e-C4' → 'c4'."""
    k = norm(s)
    for suf in ELECTRIC_SUFFIXES:
        if k.endswith(suf) and len(k) > len(suf) + 1:
            k = k[: -len(suf)]
            break
    return re.sub(r"^e(?=\d|c\d)", "", k)


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
