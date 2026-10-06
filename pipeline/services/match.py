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
    words = {w for w in re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", re.sub(r"\d+(?:\.\d+)?\s*kwh?", " ", s))}
    words = {w for w in words if w not in STOP and not w.isdigit()}
    return {"kw": int(kw.group(1)) if kw else None, "kwh": round(float(kwh.group(1))) if kwh else None,
            "seats": int(seats.group(1)) if seats else None, "words": words}


def score(derivative: str, car: dict) -> int | None:
    """None = contradiction; else how many of the car's trim words the text shares."""
    d = tokens(derivative)
    c = tokens(f"{car.get('trim') or ''} {car.get('variant') or ''}")
    if car.get("battery_kwh") and c["kwh"] is None:
        c["kwh"] = round(float(car["battery_kwh"]))
    for k in ("kw", "kwh"):
        if d[k] is not None and c[k] is not None and d[k] != c[k]:
            return None
    if d["seats"] and car.get("seats") and d["seats"] != car["seats"]:
        return None
    trim_words = set(tokens(car.get("trim") or "")["words"])
    if trim_words and not trim_words <= d["words"]:
        return None
    return len(trim_words & d["words"]) + (1 if d["kw"] is not None and c["kw"] == d["kw"] else 0) \
        + (1 if d["kwh"] is not None and c["kwh"] == d["kwh"] else 0)


def best(derivative: str, candidates: list[dict]) -> dict | None:
    """The single best-scoring candidate, or None when there is none or a tie."""
    scored = [(score(derivative, c), c) for c in candidates]
    scored = [(s, c) for s, c in scored if s is not None]
    if not scored:
        return None
    scored.sort(key=lambda sc: -sc[0])
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None
    return scored[0][1]
