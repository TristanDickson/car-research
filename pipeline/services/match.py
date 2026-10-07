"""Match a broker's derivative text to a generated car of the same model.

LeaseLoco and New Car Discount name a derivative in their own words
('150kW GT-Line S 81.4kWh 5dr Auto [Heat Pump]'); Carwow's generated cars carry
the trim and engine as Carwow prints them ('GT-Line S · 150kW 81.4kWh Auto').
Both agree on the numbers that identify a powertrain (kW, kWh) and on the trim
words, so a derivative resolves to the one generated car whose kW and kWh agree
(where both print them) and whose trim words all appear in the derivative. Two
candidates scoring the same is a miss, never a guess: the row stays unmapped
for a human to decide.

Hand-curated cars are never matched this way; the seed's trim map names them.
Twins (several derivatives of one trim and powertrain) are told apart by
services/resolve.py, which owns the RRP, bracket and version rules.
"""
from __future__ import annotations

import re

STOP = {"5dr", "4dr", "3dr", "2dr", "auto", "automatic", "electric", "estate", "hatchback", "saloon", "suv", "coupe",
        "mpv", "van", "dr", "ev", "e", "bev", "the", "and", "with", "pack", "edition", "awd", "rwd", "fwd", "4wd",
        "2wd", "long", "range", "standard", "extended", "comfort", "urban", "seat", "seats"}


def tokens(s: str) -> dict:
    s = (s or "").lower()
    kw = re.search(r"(\d+)\s*kw(?!h)", s)
    kwh = re.search(r"(\d+(?:\.\d+)?)\s*kwh", s)
    seats = re.search(r"\[?(\d)\s*seat", s)
    # 'GT+' and 'Techno +' are trims of their own: the plus stays on its word.
    body = re.sub(r"\s+\+", "+", re.sub(r"\d+(?:\.\d+)?\s*kwh?", " ", s))
    # Numbers stay: Hyundai's trims are '01' and '02', Skoda's engines '60' and '85'.
    words = {w for w in re.findall(r"[a-z0-9+]+(?:-[a-z0-9+]+)*", body)}
    words = {w for w in words if w not in STOP and w != "+"}
    return {"kw": int(kw.group(1)) if kw else None, "kwh": round(float(kwh.group(1))) if kwh else None,
            "seats": int(seats.group(1)) if seats else None, "words": words}


def _parts(car: dict) -> tuple[str, str]:
    """A generated car's trim and engine ('GT-Line S · 150kW 81.4kWh Auto')."""
    trim = car.get("trim") or ""
    if " · " in trim:
        t, _, e = trim.partition(" · ")
        return t, car.get("variant") or e
    return trim, car.get("variant") or ""


def score(derivative: str, car: dict) -> int | None:
    """None = contradiction (kW, kWh or seats disagree, or a trim word is missing
    from the text); else a score: trim words count double, engine words
    ('Quattro', 'Performance', 'Extended Range') are a bonus the broker may omit."""
    d = tokens(derivative)
    trim, engine = _parts(car)
    c = tokens(f"{trim} {engine}")
    if car.get("battery_kwh") and c["kwh"] is None:
        c["kwh"] = round(float(car["battery_kwh"]))
    for k in ("kw", "kwh"):
        if d[k] is not None and c[k] is not None and d[k] != c[k]:
            return None
    trim_words = tokens(trim)["words"]
    if trim_words and not trim_words <= d["words"]:
        return None
    engine_words = tokens(engine)["words"]
    return 2 * len(trim_words & d["words"]) + len(engine_words & d["words"]) \
        + (1 if d["kw"] is not None and c["kw"] == d["kw"] else 0) + (1 if d["kwh"] is not None and c["kwh"] == d["kwh"] else 0)


def _powertrain(car: dict) -> tuple[str, int | None, int | None]:
    trim, engine = _parts(car)
    c = tokens(engine)
    kwh = c["kwh"] if c["kwh"] is not None else (round(float(car["battery_kwh"])) if car.get("battery_kwh") else None)
    return trim.lower(), c["kw"], kwh


def best(derivative: str, candidates: list[dict]) -> dict | None:
    """The single best-scoring candidate, or None when there is none or a tie.

    Carwow often lists several derivatives of one trim and powertrain that
    differ only by option packs, spelling ('Quattro Perf' / 'Qtro Perf') and
    RRP; a broker's price for that trim and powertrain goes on the cheapest of
    them, the base derivative. A tie between different trims or powertrains is
    a miss."""
    scored = [(score(derivative, c), c) for c in candidates]
    scored = [(s, c) for s, c in scored if s is not None]
    if not scored:
        return None
    scored.sort(key=lambda sc: -sc[0])
    top = [c for s, c in scored if s == scored[0][0]]
    if len({_powertrain(c) for c in top}) > 1:
        return None
    return min(top, key=lambda c: (c.get("list_price_gbp") is None, c.get("list_price_gbp") or 0, c["id"]))
