"""Which derivative does a broker's text name? The resolution rules, in order.

A broker row (LeaseLoco, New Car Discount) carries CAP's own derivative name:
'150kW GT-Line S 81.4kWh 5dr Auto [Heat Pump]'. Carwow's pages carry the CAP id
and RRP but print only trim and engine, so a trim often has several derivatives
on Carwow that differ by RRP alone (option packs, a heat pump, a seat layout:
see docs/ARCHITECTURE.md, "Transform"). Resolution is linkage to that
registry, not clustering: every broker row names one CAP derivative.

  exact       a candidate whose registry CAP name is the text exactly as printed
              is the only one weighed: no gate or score reads it first
  gates       make + model agree, kW and kWh agree where both print them, every
              trim word of the candidate appears in the text (services/match.py),
              both read alike by pipeline/normalise.py
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
  price       the record's own price (car_ref.rrp) is no list price the text's
              derivatives could carry: below the cheapest by more than rounding,
              or above the dearest by more than paint and options. Dealers copy
              derivative lines between pages (RRG's EV6 example says 'Air' at the
              GT-Line's £52,835), so the price outranks the text: a conflict

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

from pipeline import gold, normalise
from pipeline.services import match

BRACKET_RE = re.compile(r"\[([^\]]+)\]")
SEATS_RE = re.compile(r"^(\d)\s*(?:seats?|st)$", re.I)   # '[7 seat]', '[7St]'
RRP_TOLERANCE = 10.0
# How far a record's own price may sit from the list price of the derivative its text names: above it by
# paint and options (a dealer's on-the-road example includes its metallic paint), below it by rounding.
PRICE_ABOVE_LIST = 1500.0
PRICE_BELOW_LIST = 250.0
EXACT = "="   # a pin filed under the name exactly as printed (pin_keys)
APPENDED_SEATS_RE = re.compile(r" \[\d seat\]$")


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
    """CAP's derivative name read as pipeline/normalise.py reads every name, minus the seat count a
    provider may append ('[4 seat]'), so two brokers' copies of one name agree."""
    t = re.sub(r"\[\s*\d\s*seats?\s*\]", " ", normalise.fold(text))
    return " ".join(normalise.name_words(t))


def printed(text: str | None) -> str:
    """The name as its source printed it: without the seat count LeaseLoco's reader appends ('[4 seat]',
    providers/leaseloco.py), which is ours, not CAP's."""
    return APPENDED_SEATS_RE.sub("", text or "")


def pin_keys(text: str | None) -> tuple[str, str]:
    """Where a pin for this name is filed and looked up: the name exactly as printed first, then its name_key."""
    return (EXACT + printed(text), name_key(text))


def _price(c: dict) -> float | None:
    return c.get("list_price_gbp")


def _current_first(c: dict) -> tuple:
    return (c.get("version_date") or "", c["id"])


def _off_price(rrp, top: list[dict]) -> dict | None:
    """Evidence that the record's own price fits none of the derivatives its text names, else None."""
    prices = [p for p in (_price(c) for c in top) if p]
    if not rrp or not prices:
        return None
    rrp = float(rrp)
    if any(p - PRICE_BELOW_LIST <= rrp <= p + PRICE_ABOVE_LIST for p in prices):
        return None
    return {"reason": "the record's price fits no derivative its text names", "rrp": rrp, "list_prices": sorted(set(prices))}


def _pinned_elsewhere(pins: dict[str, set[str]] | None, text: str, twin_ids: set[str]) -> str | None:
    """The twin another source's copy of the same CAP name was pinned to by its RRP: the name as printed
    first, then as read alike."""
    if not pins or not text:
        return None
    for key in pin_keys(text):
        hit = sorted((pins.get(key) or set()) & twin_ids)
        if len(hit) == 1:
            return hit[0]
    return None


def choose(ref: dict, candidates: list[dict], pins: dict[str, set[str]] | None = None) -> Resolution:
    """The one derivative `ref` names, with how we know. `ref` is the record's
    car_ref: derivative (the broker's text), optional rrp; `candidates` the
    derivatives of that make + model; `pins` the CAP names other records were
    pinned to by their RRP (pin_keys -> derivative ids), from a first pass.
    A candidate of the record's own model whose registry name is the text exactly
    as printed is taken before any is scored, so reading names alike can never lose
    an exact match (the Q4 and Q4 Sportback share CAP names: the model decides)."""
    text = ref.get("derivative") or ref.get("label") or ""
    named = [c for c in candidates if text and c.get("cap_name") == printed(text) and gold.model_is(ref.get("model"), c, ref.get("make"))]
    if named:
        top, best = named, "exact name"
    else:
        scored = [(s, c) for s, c in ((match.score(text, c), c) for c in candidates) if s is not None]
        if not scored:
            return Resolution(None, "none", {"candidates": len(candidates)})
        scored.sort(key=lambda sc: -sc[0])
        top, best = [c for s, c in scored if s == scored[0][0]], scored[0][0]
    if len({match._powertrain(c) for c in top}) > 1:
        return Resolution(None, "none", {"reason": "tie between different trims or powertrains",
                                         "tied": sorted(c["id"] for c in top)})
    br = brackets(text)
    ev = {"score": best, "twins": sorted(c["id"] for c in top), "prices": sorted({_price(c) for c in top if _price(c)}),
          "brackets": br}
    off = _off_price(ref.get("rrp"), top)
    if off:
        return Resolution(None, "conflict", {**ev, **off}, br)
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
    pinned = _pinned_elsewhere(pins, text, {c["id"] for c in top})
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
