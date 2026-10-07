"""Which derivative does a broker's text name? The resolution rules, in order.

A broker row (LeaseLoco, New Car Discount) carries CAP's own derivative name:
'150kW GT-Line S 81.4kWh 5dr Auto [Heat Pump]'. Carwow's pages carry the CAP id
and RRP but print only trim and engine, so a trim often has several derivatives
on Carwow that differ by RRP alone (option packs, a heat pump, a seat layout:
see docs/ARCHITECTURE.md, "Generated cars"). Resolution is linkage to that
registry, not clustering: every broker row names one CAP derivative.

  gates       make + model agree, kW and kWh agree where both print them, every
              trim word of the candidate appears in the text (services/match.py)
  one match   a single candidate after the gates: 'trim-powertrain'
  twins       several derivatives of one trim and powertrain, told apart by:
    rrp         the broker's own RRP (NCD prints price + saving) equals one twin's
    name        the same CAP name was pinned to a twin by another source already
    bracket     a pack in the name ('[Heat Pump]', '[Tech Pack]', '[7 seat]')
                belongs to the dearer twin when there are exactly two prices;
                '[No Heat Pump]' or no bracket to the cheapest
    version     identical prices: the current price-list version, then the id
  conflict    a pack bracket against three or more prices with no RRP to anchor
              on: recorded, never guessed

A bracket that picked a twin also tells us something about that twin, which a
Carwow page never prints: the name is written onto the generated car as a pack,
'[Heat Pump]' sets its heat pump to standard, '[No Heat Pump]' to none, and
'[7 seat]' its seats. Every resolution records its method and evidence on the
trim map so the Data page can show why a lease sits on a car.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field

from pipeline.services import match

BRACKET_RE = re.compile(r"\[([^\]]+)\]")
SEATS_RE = re.compile(r"^(\d)\s*(?:seats?|st)$", re.I)   # '[7 seat]', '[7St]'
RRP_TOLERANCE = 10.0


@dataclass
class Resolution:
    car_id: str | None
    method: str              # trim-powertrain | rrp | name | bracket | base | version | conflict | none
    evidence: dict = field(default_factory=dict)
    brackets: list[str] = field(default_factory=list)


def brackets(text: str | None) -> list[str]:
    return [b.strip() for b in BRACKET_RE.findall(text or "") if b.strip()]


def pack_brackets(text: str | None) -> list[str]:
    """Brackets that name something fitted (not a 'No …' and not a plain seat count)."""
    return [b for b in brackets(text) if not b.lower().startswith("no ") and not SEATS_RE.match(b)]


def name_key(text: str | None) -> str:
    """CAP's derivative name as printed, lower-cased, minus the seat count a
    provider may append ('[4 seat]'), so two brokers' copies of one name agree."""
    t = re.sub(r"\[\s*\d\s*seats?\s*\]", " ", (text or "").lower())
    return re.sub(r"\s+", " ", t).strip()


def _price(c: dict) -> float | None:
    return c.get("list_price_gbp")


def _current_first(c: dict) -> tuple:
    return (c.get("version_date") or "", c["id"])


def _pinned_elsewhere(conn: sqlite3.Connection | None, key: str, twin_ids: set[str]) -> str | None:
    if conn is None or not key:
        return None
    try:
        rows = conn.execute(
            "SELECT car_id FROM trim_map WHERE name_key=? AND status='auto' AND method IN ('rrp', 'name') AND car_id IS NOT NULL",
            (key,),
        ).fetchall()
    except sqlite3.OperationalError:
        return None
    for r in rows:
        if r[0] in twin_ids:
            return r[0]
    return None


def choose(ref: dict, candidates: list[dict], conn: sqlite3.Connection | None = None) -> Resolution:
    """The one generated car `ref` names, with how we know. `ref` is the record's
    car_ref: derivative (the broker's text), optional rrp; `candidates` the
    generated cars of that make + model."""
    text = ref.get("derivative") or ref.get("label") or ""
    scored = [(s, c) for s, c in ((match.score(text, c), c) for c in candidates) if s is not None]
    if not scored:
        return Resolution(None, "none", {"candidates": len(candidates)})
    scored.sort(key=lambda sc: -sc[0])
    top = [c for s, c in scored if s == scored[0][0]]
    if len({match._powertrain(c) for c in top}) > 1:
        return Resolution(None, "none", {"reason": "tie between different trims or powertrains",
                                         "tied": sorted(c["id"] for c in top)})
    br = brackets(text)
    ev = {"score": scored[0][0], "twins": sorted(c["id"] for c in top), "prices": sorted({_price(c) for c in top if _price(c)}),
          "brackets": br}
    if len(top) == 1:
        return Resolution(top[0]["id"], "trim-powertrain", ev, br)

    # Twins: one trim and powertrain, several derivatives.
    rrp = ref.get("rrp")
    if rrp:
        exact = [c for c in top if _price(c) and abs(_price(c) - float(rrp)) <= RRP_TOLERANCE]
        if exact:
            pick = max(exact, key=_current_first)
            return Resolution(pick["id"], "rrp", {**ev, "rrp": rrp}, br)
        ev["rrp_unmatched"] = rrp
    pinned = _pinned_elsewhere(conn, name_key(text), {c["id"] for c in top})
    if pinned:
        return Resolution(pinned, "name", {**ev, "name_key": name_key(text)}, br)
    packs = pack_brackets(text)
    prices = sorted({_price(c) for c in top if _price(c)})
    if packs:
        if len(prices) == 2:
            dearer = [c for c in top if _price(c) == prices[-1]]
            pick = max(dearer, key=_current_first)
            return Resolution(pick["id"], "bracket", {**ev, "packs": packs}, br)
        if len(prices) > 2:
            return Resolution(None, "conflict", {**ev, "packs": packs, "reason": "a pack against three or more prices and no RRP"}, br)
    if len(prices) > 1:
        cheapest = [c for c in top if _price(c) == prices[0]]
        pick = max(cheapest, key=_current_first)
        return Resolution(pick["id"], "base", ev, br)
    pick = max(top, key=_current_first)
    return Resolution(pick["id"], "version", ev, br)


def facts_from_brackets(car: dict, br: list[str]) -> dict:
    """What the brackets say about the derivative, as car fields to merge in.
    Only for generated cars; a hand-curated car already knows."""
    if not car.get("auto") or not br:
        return {}
    out: dict = {}
    packs = [b for b in br if not SEATS_RE.match(b)]
    if packs:
        out["packs"] = sorted(set((car.get("packs") or []) + packs))
    low = [b.lower() for b in br]
    if any(b == "no heat pump" for b in low):
        out["heat_pump"] = "none"
    elif any("heat pump" in b and not b.startswith("no ") for b in low):
        out["heat_pump"] = "standard"
    for b in br:
        m = SEATS_RE.match(b)
        if m:
            out["seats"] = int(m.group(1))
    return out


def dump_evidence(ev: dict) -> str:
    return json.dumps(ev, ensure_ascii=False, sort_keys=True)
