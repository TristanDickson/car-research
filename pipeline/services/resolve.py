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
    name        the same CAP name was pinned to a twin by another source's RRP
    bracket     a pack in the name ('[Heat Pump]', '[Tech Pack]', '[7 seat]')
                belongs to the dearer twin when there are exactly two prices;
                '[No Heat Pump]' or no bracket to the cheapest
    version     identical prices: the current price-list version, then the id
  conflict    a pack bracket against three or more prices with no RRP to anchor
              on: recorded, never guessed

A bracket that picked a twin also tells us something about that twin, which a
Carwow page never prints; the claim store reads it from the resolved names
(services/claims.py, from_broker_labels). Every resolution records its method and
evidence so the Data page can show why a lease sits on a car. The rules run over
every record at once (pipeline/build.py): the 'name' rule reads the pins a first
pass made by RRP, so no answer depends on the order records were read in.
"""
from __future__ import annotations

import json
import re
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


def _pinned_elsewhere(pins: dict[str, set[str]] | None, key: str, twin_ids: set[str]) -> str | None:
    """The twin another source's copy of the same CAP name was pinned to by its RRP."""
    if not pins or not key:
        return None
    hit = sorted((pins.get(key) or set()) & twin_ids)
    return hit[0] if len(hit) == 1 else None


def choose(ref: dict, candidates: list[dict], pins: dict[str, set[str]] | None = None) -> Resolution:
    """The one derivative `ref` names, with how we know. `ref` is the record's
    car_ref: derivative (the broker's text), optional rrp; `candidates` the
    derivatives of that make + model; `pins` the CAP names other records were
    pinned to by their RRP (name key -> derivative ids), from a first pass."""
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
    pinned = _pinned_elsewhere(pins, name_key(text), {c["id"] for c in top})
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


def dump_evidence(ev: dict) -> str:
    return json.dumps(ev, ensure_ascii=False, sort_keys=True)
