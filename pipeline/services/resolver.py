"""The resolver (docs/ARCHITECTURE-NEXT.md, "Transform", steps 2 to 5; BOARD.md, T3): every record that names a car,
from every source, filtered against one master list of cars, with why each was placed where it was.

  cars       every derivative Parkers lists, old generations included (master_list), and each Carwow derivative no
             Parkers entry can be: newer than Parkers' list, or of a model Parkers does not file. A car's id is built
             from its details (car_key: make, model, generation, kW, trim, the motor's other words, kWh, doors, seats,
             packs), so it is the same whichever record lists it first, and two names that read alike ('Qtro Perf' and
             'Quattro Performance') are one car.
  versions   a car's battery, motor and drive within its generation (version_of).
  compounds  the details read off each record (Compound): its Carwow model (Parkers' through services/model_map.py),
             CAP id, CAP-style name, trim words, kW, kWh (a label, or EV Database's usable figure), drive, seats,
             doors, a date and what kind, a list price, packs, fuel.
  filter     within the record's model, every detail it gives rules out the cars it contradicts (RULES, with the
             tolerances below); a detail it does not give rules nothing out. A record whose CAP-style name is a car's
             name exactly as printed is filtered against those cars first.
  decide     one left is the car. Several: the record's list price, then its pack names, narrow them; what is still
             left goes on the best spec of them with the others named (BOARD.md, T7). None: a Carwow derivative with
             its own trim and motor becomes a car; any other record stays at its version or model and is listed.
  CAP id     the derivative a CAP id names is decided from every Carwow record that describes it (the registry line,
             the specification row, the deals card), with the CAP-style name any record printing the id gives; every
             record printing the id then goes to that car unless one of its own details contradicts it, which is
             listed.
  EV Database  a variant describes a version: it goes to the version its details leave, with every car of it.
  rounds     a CAP id placed on one car gives that car Carwow's name and list price, which the next round reads (a
             second price list's copy of a derivative finds it by name, a twin by price); the rounds repeat until no
             CAP id's car changes. Each round reads only the previous round's state and every choice is a maximum
             over all candidates, ties broken by id, so no answer depends on the order the records came in.

Nothing here is typed in by hand: the cars, their trims and dates are Parkers' and Carwow's, the models' mapping is
services/model_map.py's. The comparison against today's lookups (compare) is for the owner to go through before the
switch; until then today's lookups still decide what the app shows.
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass, field, replace

from pipeline import gold, normalise
from pipeline.providers.parse import combustion
from pipeline.providers.used_match import match_model
from pipeline.services import claims, facts, model_map, snapshot

# Tolerances (docs/ARCHITECTURE-NEXT.md, "Filter").
KW_TOLERANCE = 5            # a motor more than 5 kW away is another motor
KWH_TOLERANCE = 0.6         # a battery label more than 0.6 kWh away is another battery ('64kWh' is not '65kWh')
USABLE_RATIO = facts.USABLE_RATIO   # EV Database's usable figure against a label: usable runs 84 to 100% of it
PRICE_BELOW_LIST = 250.0    # a record's list price may sit below a car's by rounding,
PRICE_ABOVE_LIST = 1500.0   # and above it by paint and options (services/resolve.py)
PRICE_SAME = 10.0           # a list price within £10 of a car's is that car's
# Dates, in months: a price list or a current offer may come up to 6 months before a car's on-sale date and up to
# 6 after its last; a car registered in a year is not one first sold in a later year, nor one off sale more than a
# year before; an EV Database variant's years must overlap the car's, within 3 months.
LISTED_BEFORE, LISTED_AFTER = 6, 6
REGISTERED_AFTER_YEARS = 1
SPAN_SLACK = 3
MAX_ROUNDS = 10

PS_KW, BHP_KW = 0.7355, 0.7457
CLASH = "clash"   # a name and its page printing different figures
BRACKET_RE = re.compile(r"\[([^\]]*)\]")
KWH_RE = re.compile(r"(\d+(?:\.\d+)?)\s*-?kwh")
KW_RE = re.compile(r"(\d+(?:\.\d+)?)\s*-?kw(?![a-z])")
PS_RE = re.compile(r"(\d+)\s*-?ps\b")
BHP_RE = re.compile(r"(\d+)\s*-?bhp\b")
DOORS_RE = re.compile(r"\b([2-5])\s*-?(?:dr|d|doors?)\b")
SEATS_RE = re.compile(r"\b([2-9])\s*-?(?:seats?|seater|st)\b")
YEARS_RE = re.compile(r"\((?:my)?\s*\d\d(?:\s*-\s*\d\d)?\)")   # EV Database's '(MY22-23)'
# The on-board charger: '22kWCh', '22kW Charger', '11kW on-board', or a second kW figure of a charger's size after the
# motor's ('Tech+/Cmf+/22kW'). A detail of its own, never the motor and never dropped.
CHARGER_RE = re.compile(r"(\d+(?:\.\d+)?)\s*-?kw\s*(?:ch\b|chg\b|charger|on[\s-]?board(?:\s+charger)?)")
CHARGER_SIZES = {6.6, 7.0, 7.2, 7.4, 11.0, 22.0}
# Body words, by the body they name (a Touring, a Tourer and an SW are estates; Porsche's two Turismos are two bodies).
BODIES = {"sport turismo": "sport turismo", "cross turismo": "cross turismo", "shooting brake": "shooting brake",
          "sportback": "sportback", "touring": "estate", "tourer": "estate", "sports tourer": "estate", "estate": "estate", "sw": "estate"}
# Words that say nothing about which derivative a name is.
NOISE = {"auto", "automatic", "at", "electric", "battery", "ev", "bev", "e", "motor", "lithium", "ion", "dr", "d", "door", "doors",
         "kw", "kwh", "ps", "bhp", "hp", "with", "and", "the"}
PACK_WORDS = {"pack", "package", "packs"}
AWD_WORDS = {"awd", "4wd", "4x4", "quattro", "4motion", "4matic", "all4"}
AWD_PHRASES = ("dual motor", "twin motor", "all wheel drive", "four wheel drive", "e 4orce", "tri motor")
RECORD_KINDS = ("offer", "used", "spec", "registry", "options", "configuration", "variant")


def _months(ym: str | None) -> int | None:
    if not ym or not re.match(r"^\d{4}-\d\d", ym):
        return None
    return int(ym[:4]) * 12 + int(ym[5:7]) - 1


def _ym(m: int | None) -> str | None:
    return f"{m // 12:04d}-{m % 12 + 1:02d}" if m is not None else None


def _num(v) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- reading a name

@dataclass(frozen=True)
class Read:
    """What a derivative's name, a trim's or a listing's text says, read alike (pipeline/normalise.py)."""
    kw: int | None = None
    kwh: float | None = None
    doors: int | None = None
    seats: int | None = None
    drive: str | None = None          # awd | rwd | fwd | 2wd
    rex: bool | None = None           # a range extender
    packs: frozenset = frozenset()    # bracketed packs, read alike ('[Lux Pack/Leather]' → lux, leather)
    bracketed: bool = False
    words: frozenset = frozenset()    # every other word
    cap_style: bool = False           # CAP's wording ('150kW Ultimate 64kWh 5dr Auto'): no bracket means no pack
    charger: float | None = None      # the on-board charger's kW, where the name prints it


def _words(text: str | None, make: str | None = None) -> list[str]:
    """normalise.name_words, a '+' after a word read as the word 'plus' ('Premium+' is premium plus, as Parkers' trim
    'premium-plus' reads); after a number it stays ('EQS 450+' is the 450+, not a Plus trim)."""
    out = []
    for w in normalise.name_words(text, make):
        out += [w[:-1], "plus"] if w.endswith("+") and w[:-1].isalpha() else [w]
    return out


def pack_tokens(text: str | None, make: str | None = None) -> frozenset:
    """A bracket's or a configurator package's packs: 'Lux Pack/Leather' → lux, leather; 'Comfort Pack (Ultimate)'
    → comfort; 'No Heat Pump' → no heat pump."""
    out = set()
    for part in re.split(r"[/,]", re.sub(r"\([^)]*\)", " ", text or "")):
        ws = [w for w in _words(part, make) if w not in PACK_WORDS]
        if ws:
            out.add(" ".join(ws))
    return frozenset(out)


def drive_of(words: list[str]) -> str | None:
    text = " ".join(words)
    if any(w in AWD_WORDS or w.startswith("xdrive") or re.fullmatch(r"\d{2,3}x", w) for w in words) \
            or any(f" {p} " in f" {text} " for p in AWD_PHRASES):
        return "awd"
    if "rwd" in words or " rear wheel drive " in f" {text} ":
        return "rwd"
    if "fwd" in words or " front wheel drive " in f" {text} ":
        return "fwd"
    if "2wd" in words or " single motor " in f" {text} ":
        return "2wd"
    return None


def drive_field(s: str | None) -> str | None:
    """A source's drive field ('Four wheel drive', 'Rear-wheel drive', 'AWD')."""
    t = normalise.fold(s)
    if not t:
        return None
    if re.search(r"four|all|awd|4wd|4x4", t):
        return "awd"
    if re.search(r"rear|rwd", t):
        return "rwd"
    if re.search(r"front|fwd", t):
        return "fwd"
    if re.search(r"2wd|two", t):
        return "2wd"
    return None


def _charger(t: str) -> tuple[str, float | None]:
    """The text without its charger figure, and the figure."""
    m = CHARGER_RE.search(t)
    if m:
        return t[:m.start()] + " " + t[m.end():], float(m.group(1))
    kws = list(KW_RE.finditer(BRACKET_RE.sub(lambda b: " " * len(b.group(0)), t)))
    for m in kws[1:]:
        if float(m.group(1)) in CHARGER_SIZES and float(m.group(1)) < float(kws[0].group(1)):
            return t[:m.start()] + " " + t[m.end():], float(m.group(1))
    return t, None


def read(text: str | None, make: str | None = None) -> Read:
    t = YEARS_RE.sub(" ", normalise.fold(text).replace("’", "'"))
    t, charger = _charger(t)
    seats, packs, bracketed = None, set(), False
    for b in BRACKET_RE.findall(t):
        m = SEATS_RE.fullmatch(b.strip())
        if m:
            seats = int(m.group(1))
        elif b.strip():
            bracketed = True
            packs |= pack_tokens(b, make)
    body = BRACKET_RE.sub(" ", t)
    kwh = KWH_RE.search(body)
    kw = KW_RE.search(body)
    ps, bhp = PS_RE.search(body), BHP_RE.search(body)
    doors = DOORS_RE.search(body)
    if seats is None and (m := SEATS_RE.search(body)):
        seats = int(m.group(1))
    power = round(float(kw.group(1))) if kw else round(int(ps.group(1)) * PS_KW) if ps else round(int(bhp.group(1)) * BHP_KW) if bhp else None
    rest = body
    for rx in (KWH_RE, KW_RE, PS_RE, BHP_RE, DOORS_RE, SEATS_RE):
        rest = rx.sub(" ", rest)
    ws = _words(rest, make)
    words = frozenset(w for w in ws if w not in NOISE)
    rex = True if re.search(r"range extender|\brex\b", t) else None
    return Read(kw=power, kwh=float(kwh.group(1)) if kwh else None, doors=int(doors.group(1)) if doors else None, seats=seats,
                drive=drive_of(ws), rex=rex, packs=frozenset(packs), bracketed=bracketed, words=words,
                cap_style=bool(kw and kwh and doors), charger=charger)


def _slug_words(ws) -> str:
    ws = [w.replace("+", " plus") for w in ws]   # '[Premium +]' is not '[Premium]'
    return "-".join(normalise.slug(w) for w in ws if normalise.slug(w))


def car_key(make: str, model: str, generation: str, trim: tuple[str, ...], r: Read, price: float | None = None) -> str:
    """A car's id, from its details: make/model/generation/kW-trim-motor words-kWh-doors-seats-packs. `price`, for a
    Carwow derivative whose packs no record prints, tells it from its twins."""
    others = sorted(r.words - set(trim))
    parts = ([f"{r.kw}kw"] if r.kw else []) + list(trim) + others + ([f"{r.kwh:g}kwh"] if r.kwh else []) \
        + ([f"{r.doors}dr"] if r.doors else []) + ([f"{r.seats}-seat"] if r.seats else []) + [f"with {p}" for p in sorted(r.packs)] \
        + ([f"{r.charger:g}kw-charger"] if r.charger else []) + ([f"gbp{price:.0f}"] if price else [])
    return f"{make}/{model}/{generation or '-'}/{_slug_words(parts) or 'derivative'}"


# ---------------------------------------------------------------- the master list

@dataclass
class Car:
    id: str
    make: str
    model: str
    generation: str
    source: str                      # parkers | carwow
    trim: tuple[str, ...]
    read: Read                       # what its name says (its id is built from this)
    kw: int | None
    kwh: float | None
    doors: int | None
    seats: int | None
    drive: str | None
    since: int | None                # months
    until: int | None
    open: bool
    names: set[str] = field(default_factory=set)
    words: set[str] = field(default_factory=set)
    prices: set[float] = field(default_factory=set)
    keys: set[str] = field(default_factory=set)       # the Parkers pages or CAP ids it was made from
    carwow_models: set[str] = field(default_factory=set)
    version: str = ""
    seen: dict = field(default_factory=dict)          # figure → every value its Parkers pages printed

    def row(self) -> dict:
        return {"id": self.id, "make": self.make, "model": self.model, "generation": self.generation, "source": self.source,
                "trim": " ".join(self.trim) or None, "kw": self.kw, "kwh": self.kwh, "doors": self.doors, "seats": self.seats,
                "drive": self.drive, "packs": sorted(self.read.packs), "since": _ym(self.since), "until": None if self.open else _ym(self.until),
                "on_sale": self.open, "prices": sorted(self.prices), "names": sorted(self.names), "keys": sorted(self.keys),
                "carwow_models": sorted(self.carwow_models), "version": self.version}

    def label(self) -> str:
        return f"{self.make}/{self.model}/{self.generation or '-'} {sorted(self.names)[0] if self.names else self.id.rsplit('/', 1)[-1]}"


def version_of(car: Car) -> str:
    """A car's version: its generation's battery, motor and drive (its motor's words where it prints no figures). Most
    names print a drive only when it is four-wheel, so the drive tells four-wheel from the rest."""
    if car.kwh or car.kw:
        motor = " ".join(x for x in (f"{car.kwh:g}kWh" if car.kwh else "", f"{car.kw}kW" if car.kw else "") if x)
    else:
        motor = " ".join(sorted(car.read.words - set(car.trim))) or "?"
    return f"{car.make}/{car.model}/{car.generation or '-'} {motor}" + (" awd" if car.drive == "awd" else "")


def pick_trim(name_words: set[str], trims: list[tuple[str, ...]]) -> tuple[str, ...]:
    """The generation's trim a derivative's name prints: the longest whose words it has all of ('N Line S' over 'N Line')."""
    fits = [t for t in trims if t and set(t) <= name_words]
    return max(fits, key=lambda t: (len(t), len("".join(t)), t)) if fits else ()


def parkers_trims(conn: sqlite3.Connection) -> dict[tuple[str, str, str], list[tuple[str, ...]]]:
    out: dict[tuple[str, str, str], set] = {}
    for p, in conn.execute("SELECT payload FROM specs WHERE source='parkers' AND spec_key LIKE 'parkers-sitemap:%/trim-%'"):
        r = json.loads(p)
        t = tuple(w for w in _words(r["slug"].replace("-", " "), r["make_slug"]) if w not in NOISE)
        out.setdefault((r["make_slug"], r["model_slug"], r["generation"]), set()).add(t)
    return {k: sorted(v) for k, v in out.items()}


def master_list(conn: sqlite3.Connection) -> tuple[dict[str, Car], dict[tuple[str, str, str], list[tuple[str, ...]]]]:
    """Every derivative Parkers lists, one car per id: its derivative page where read, else its sitemap address."""
    trims = parkers_trims(conn)
    pages: dict[str, dict] = {}
    paths: dict[str, dict] = {}
    for key, payload in conn.execute("SELECT spec_key, payload FROM specs WHERE source='parkers' ORDER BY spec_key"):
        p = json.loads(payload)
        if key.startswith("parkers-sitemap:"):
            if p.get("entry") == "derivative":
                paths[key.split(":", 1)[1]] = p
        elif p.get("name"):
            pages[key.split(":", 1)[1]] = p
    cars: dict[str, Car] = {}
    for path in sorted(set(paths) | set(pages)):
        page, site = pages.get(path), paths.get(path) or {}
        mk, md, gen = (page or site).get("make_slug"), (page or site).get("model_slug"), (page or site).get("generation")
        if mk and md and gen:
            add_entry(cars, path, mk, md, gen, page["name"] if page else site["slug"].replace("-", " "), trims.get((mk, md, gen), []), page)
    return cars, trims


def add_entry(cars: dict[str, Car], path: str, mk: str, md: str, gen: str, name: str, trims: list[tuple[str, ...]],
              page: dict | None) -> Car | None:
    """One Parkers derivative onto the master list: a car of its own, or one more name of the car whose details it
    shares. `page` is its derivative page (dates, price, figures), None for an address the sitemap alone names."""
    if combustion(name):
        return None
    r = read(name, mk)
    trim = pick_trim(set(r.words), trims)
    nums = (page or {}).get("numbers") or {}
    cid = car_key(mk, md, gen, trim, r)
    car = cars.get(cid)
    since, until = _months((page or {}).get("on_sale_since")), _months((page or {}).get("on_sale_until"))
    bhp = _num(nums.get("power_bhp"))
    # The page's own figure where the name prints none; where they differ (the i5 Touring's names copy the saloon's
    # '4dr', its page says 5) neither is taken.
    page_doors = int(_num(nums.get("doors"))) if _num(nums.get("doors")) else None
    # Each figure as its name prints it, else as its page does.
    figures = {"kw": ("name", r.kw) if r.kw else ("page", round(bhp * BHP_KW) if bhp else None),
               "kwh": ("name", r.kwh) if r.kwh else ("page", _num(nums.get("battery_kwh"))),
               "doors": ("name", r.doors if page_doors in (None, r.doors) else CLASH) if r.doors else ("page", page_doors)}
    if car is None:
        car = cars[cid] = Car(cid, mk, md, gen, "parkers", trim, r, kw=None, kwh=None, doors=None, seats=r.seats, drive=r.drive,
                              since=since, until=until, open=bool(page) and until is None)
    else:
        car.since = min((x for x in (car.since, since) if x is not None), default=None)
        car.until = max((x for x in (car.until, until) if x is not None), default=None)
        car.open = car.open or (bool(page) and until is None)
    # Pages that share a car: the figure their names print, else the one their pages agree on, else none, whichever
    # page comes first.
    for f, (where, v) in figures.items():
        if v is not None:
            car.seen.setdefault((f, where), set()).add(v)
        vals = car.seen.get((f, "name")) or car.seen.get((f, "page")) or set()
        setattr(car, f, next(iter(vals)) if len(vals) == 1 and CLASH not in vals else None)
    car.names.add(name)
    car.words |= set(r.words) | {w for p in r.packs for w in p.split()}
    if page and _num(page.get("price_new")):
        car.prices.add(float(page["price_new"]))
    car.keys.add(f"parkers:{path}")
    return car


# ---------------------------------------------------------------- compounds

@dataclass
class Compound:
    """The details one record gives: what the filter reads."""
    source: str
    kind: str                         # one of RECORD_KINDS
    key: str
    label: str
    make: str | None = None
    model: str | None = None          # the Carwow catalogue model, make/model
    cap: str | None = None            # the Carwow CAP id it prints
    name: str | None = None           # a CAP-style name as printed, for the exact match
    trim: tuple[str, ...] = ()        # the words of a trim field of its own
    read: Read = Read()
    kw: int | None = None
    kwh: float | None = None
    usable: float | None = None       # EV Database's usable battery
    drive: str | None = None
    seats: int | None = None
    doors: int | None = None
    rex: bool | None = None
    date: int | None = None           # months
    date_kind: str | None = None      # listed | seen | registered | span
    span: tuple[int | None, int | None] | None = None
    price: float | None = None        # a list price
    packs: frozenset | None = None    # None: the record does not say
    describes: str = "car"            # car | version (EV Database) | trim (a maker's grade table)
    ignored: str | None = None
    today: tuple[str, ...] = ()       # today's car ids (the current lookups)
    extra: dict = field(default_factory=dict)

    def names_anything(self) -> bool:
        """Whether it names a trim, a motor or a battery: a Carwow used card of price and year alone does not."""
        return bool(self.trim or self.kw or self.kwh or self.read.words)

    def details(self) -> dict:
        d = {"make": self.make, "model": self.model, "cap_id": self.cap, "name": self.name, "trim": " ".join(self.trim) or None,
             "kw": self.kw, "kwh": self.kwh, "usable_kwh": self.usable, "drive": self.drive, "seats": self.seats, "doors": self.doors,
             "range_extender": self.rex, "date": _ym(self.date), "date_kind": self.date_kind if self.date is not None else None,
             "years": [_ym(self.span[0]), _ym(self.span[1])] if self.span else None, "list_price": self.price,
             "packs": sorted(self.packs) if self.packs is not None else None,
             "words": sorted(self.read.words) or None}
        return {k: v for k, v in d.items() if v not in (None, [], "")}


def compound(source: str, kind: str, key: str, text: str | None, *, make: str | None, model: str | None, label: str | None = None,
             cap: str | None = None, trim: str | None = None, kw=None, kwh=None, usable=None, drive=None, seats=None, doors=None,
             rex=None, date: str | None = None, date_kind: str | None = None, span=None, price=None, packs=None,
             describes: str = "car", today=(), name: str | None = None) -> Compound:
    """A record's compound: its text read (read), and the fields it prints of its own, which win over what its text says."""
    mk = normalise.make_key(make) if make else None
    r = read(" ".join(x for x in (text, trim) if x), make)
    tw = tuple(w for w in _words(trim, make) if w not in NOISE) if trim else ()
    burns = combustion(f"{text or ''} {trim or ''}")
    c = Compound(source, kind, key, label or text or key, make=mk, model=model, cap=cap, name=name, trim=tw,
                 read=Read(**{**r.__dict__, "words": frozenset(set(r.words) | set(tw))}),
                 kw=int(round(float(kw))) if _num(kw) else r.kw, kwh=_num(kwh) or r.kwh, usable=_num(usable),
                 drive=drive or r.drive, seats=int(_num(seats)) if _num(seats) else r.seats, doors=int(_num(doors)) if _num(doors) else r.doors,
                 rex=rex if rex is not None else r.rex, date=_months(date), date_kind=date_kind if date or span else None, span=span,
                 price=_num(price), packs=packs if packs is not None else (r.packs if (r.bracketed or r.cap_style) else None),
                 describes=describes, today=tuple(sorted(set(today))), ignored="its name burns fuel" if burns else None)
    return c


# ---------------------------------------------------------------- the filter

@dataclass
class Evidence:
    """What placements fixed about each car: the CAP names and list prices of the Carwow derivatives placed on it."""
    names: dict[str, set[str]] = field(default_factory=dict)
    prices: dict[str, set[float]] = field(default_factory=dict)
    caps: dict[str, set[str]] = field(default_factory=dict)

    def car_names(self, car: Car) -> set[str]:
        return car.names | self.names.get(car.id, set())

    def car_prices(self, car: Car) -> set[float]:
        return car.prices | self.prices.get(car.id, set())


def _drives_clash(a: str | None, b: str | None) -> bool:
    if not a or not b or a == b:
        return False
    return not ({a, b} <= {"2wd", "rwd", "fwd"} and "2wd" in (a, b))


def _date_reason(c: Compound, car: Car) -> str | None:
    s, u = car.since, None if car.open else car.until
    if c.date_kind == "span" and c.span:
        a, b = c.span
        if s is not None and b is not None and b < s - SPAN_SLACK:
            return f"its years ({_ym(a) or '?'} to {_ym(b)}) end before the car went on sale ({_ym(s)})"
        if u is not None and a is not None and a > u + SPAN_SLACK:
            return f"its years start ({_ym(a)}) after the car left sale ({_ym(u)})"
        return None
    if c.date is None:
        return None
    if c.date_kind == "registered":
        y = c.date // 12
        if s is not None and y < s // 12:
            return f"registered in {y}, before the car went on sale ({_ym(s)})"
        if u is not None and y > u // 12 + REGISTERED_AFTER_YEARS:
            return f"registered in {y}, after the car left sale ({_ym(u)})"
        return None
    what = "listed" if c.date_kind == "listed" else "seen"
    if s is not None and c.date < s - LISTED_BEFORE:
        return f"{what} {_ym(c.date)}, before the car went on sale ({_ym(s)})"
    if u is not None and c.date > u + LISTED_AFTER:
        return f"{what} {_ym(c.date)}, after the car left sale ({_ym(u)})"
    return None


def names_car(c: Compound, car: Car) -> bool:
    """Whether a record's text names the car outright: every word and every pack of the car's name, and no other pack."""
    if not (car.read.words or car.read.packs):
        return False
    return set(car.read.words) <= set(c.read.words) and car.read.packs == (c.packs or frozenset()) \
        and (car.read.charger is None or car.read.charger == c.read.charger)


def _bodies(text: str) -> set[str]:
    t = f" {text} "
    return {body for words, body in BODIES.items() if f" {words} " in t}


def car_bodies(car: Car) -> set[str]:
    return _bodies(" ".join([normalise.fold(car.generation.replace("-", " "))] + [normalise.fold(n) for n in sorted(car.names)]))


def rule_out(c: Compound, car: Car, vocab: set[str], trims: bool = True, dates: bool = True) -> tuple[str, str] | None:
    """(rule, why) when a detail the record gives contradicts the car; None when nothing does. `trims` False leaves
    the trim and packs out (the price rule: the car whose price a dealer's line copied is of another trim); `dates`
    False leaves the dates out (an offer seen now of a car its text names outright: a dealer's run-out stock)."""
    if c.rex is not None and bool(car.read.rex) != c.rex:
        return "fuel", "a range extender" if c.rex else "not a range extender"
    if c.kw is not None and car.kw is not None and abs(c.kw - car.kw) > KW_TOLERANCE:
        return "motor", f"{c.kw} kW, the car {car.kw} kW"
    if car.kwh is not None:
        if c.kwh is not None and abs(c.kwh - car.kwh) > KWH_TOLERANCE:
            return "battery", f"{c.kwh:g} kWh, the car {car.kwh:g} kWh"
        if c.kwh is None and c.usable is not None:
            ratio = c.usable / car.kwh
            if not (USABLE_RATIO[0] <= ratio <= USABLE_RATIO[1] + 0.03):
                return "battery", f"{c.usable:g} kWh usable cannot be the car's {car.kwh:g} kWh"
    if _drives_clash(c.drive, car.drive):
        return "drive", f"{c.drive}, the car {car.drive}"
    if c.seats is not None and car.seats is not None and c.seats != car.seats:
        return "seats", f"{c.seats} seats, the car {car.seats}"
    if c.doors is not None and car.doors is not None and c.doors != car.doors:
        return "doors", f"{c.doors} doors, the car {car.doors}"
    if c.read.charger is not None and car.read.charger is not None and c.read.charger != car.read.charger:
        return "charger", f"a {c.read.charger:g} kW charger, the car's {car.read.charger:g} kW"
    why = _date_reason(c, car) if dates else None
    if why:
        return "date", why
    # EV Database names a body that is not the plain one ('Taycan 4 Cross Turismo', 'i5 Touring'); a car of another body
    # is not it. A name without one rules nothing out, since a maker's estate is not always called one.
    mine = _bodies(normalise.fold(c.label)) if c.describes == "version" else set()
    if mine and mine != car_bodies(car):
        return "body", f"its body ({', '.join(sorted(mine))}), the car's ({', '.join(sorted(car_bodies(car))) or 'the plain body'})"
    # EV Database's words name its versions ('Long', 'Performance', 'Turbo S'), not trims.
    if not trims or c.describes == "version":
        return None
    # A Carwow derivative's CAP name is the derivative: one with other packs is another derivative.
    if c.kind == "derivative" and c.packs is not None and car.read.packs != c.packs:
        return "packs", f"its packs ({', '.join(sorted(c.packs)) or 'none'}), the car's ({', '.join(sorted(car.read.packs)) or 'none'})"
    have = set(c.read.words)
    said = have & vocab
    # A CAP-style name prints its trim, so one that leaves out the car's says it is not that car ('450e 230kW Direct4
    # Premium + 71 kWh' is not the Takumi); any other text speaks of a trim only where it prints one.
    if said or c.read.cap_style:
        if car.trim and not set(car.trim) <= have:
            return "trim", f"the car's trim ({' '.join(car.trim)}) is not in its name"
        missing = said - car.words
        if missing:
            return "trim", f"'{' '.join(sorted(missing))}' is not in the car's name"
    return None


def _band(price: float, prices: set[float]) -> bool:
    return any(p - PRICE_BELOW_LIST <= price <= p + PRICE_ABOVE_LIST for p in prices)


@dataclass
class Link:
    level: str                        # car | version | model | none | ignored
    status: str                       # placed | tied | new car | listed | contradicts | ignored
    car: str | None = None
    others: tuple[str, ...] = ()
    version: str | None = None
    why: str = ""
    decided_by: tuple[str, ...] = ()  # the details that decided it
    ruled: dict = field(default_factory=dict)   # rule → how many cars it ruled out

    def cars(self, versions: dict[str, list[str]] | None = None) -> tuple[str, ...]:
        """The cars it reaches: its car and the others named on it, or every car of its version."""
        if self.level == "version":
            return tuple(versions.get(self.version, ())) if versions is not None and self.version else ()
        if self.level == "car":
            return tuple(x for x in (self.car, *self.others) if x)
        return ()

    def row(self) -> dict:
        return {"level": self.level, "status": self.status, "car": self.car, "others": list(self.others), "version": self.version,
                "why": self.why, "decided_by": list(self.decided_by), "ruled_out": self.ruled}


def _ruled_text(ruled: Counter, examples: dict[str, str]) -> str:
    return "; ".join(f"its {rule} ruled out {n} ({examples[rule]})" for rule, n in sorted(ruled.items(), key=lambda kv: (-kv[1], kv[0])))


def _best_spec(cars: list[Car], ev: Evidence) -> Car:
    """The best equipped: the most packs fitted ('No X' counts against), then the dearest list price, then the id."""
    def rank(car: Car) -> tuple:
        packs = sum(-1 if p.startswith("no ") else 1 for p in car.read.packs)
        return (packs, max(ev.car_prices(car), default=0.0), car.id)
    return max(cars, key=rank)


class Resolver:
    """Every compound against the cars of its model (pure: the same inputs give the same links in any order)."""

    def __init__(self, cars: dict[str, Car], pools: dict[str, list[str]], vocab: dict[str, set[str]],
                 siblings: dict[str, list[str]] | None = None):
        self.cars, self.pools, self.vocab = cars, pools, vocab
        self.siblings = siblings or {}   # Carwow model → the other Carwow models filed under its Parkers model
        self.versions: dict[str, list[str]] = {}
        for car in sorted(cars.values(), key=lambda c: c.id):
            self.versions.setdefault(car.version, []).append(car.id)

    def pool(self, c: Compound) -> list[Car]:
        return [self.cars[i] for i in self.pools.get(c.model or "", [])]

    def filter(self, c: Compound, cands: list[Car], ev: Evidence, pool: list[Car] | None = None) -> tuple[list[Car], Counter, dict[str, str]]:
        vocab = self.vocab.get(c.model or "", set())
        left, ruled, ex = [], Counter(), {}
        seen_now = c.date_kind == "seen"
        for car in cands:
            r = rule_out(c, car, vocab, dates=not (seen_now and names_car(c, car)))
            if r:
                ruled[r[0]] += 1
                ex.setdefault(r[0], r[1])
            else:
                left.append(car)
        # A charger the record prints is the car whose name prints it, where one does; a name without one is another car.
        if c.read.charger is not None and len(left) > 1:
            fitted = [car for car in left if car.read.charger == c.read.charger]
            if fitted and len(fitted) < len(left):
                ruled["charger"] += len(left) - len(fitted)
                ex.setdefault("charger", f"its {c.read.charger:g} kW charger is in {len(fitted)} of their names")
                left = fitted
        # A price no car left could have, which is the list price of a car its text rules out by trim alone: a dealer's
        # line copied from another derivative (RRG's EV6 'Air' at the GT-Line's £52,835). Only a current price list's or
        # offer's: a used car's price when new is of its registration. A price fitting none and no such car either is a
        # price list's change (the Polestar 4 Rear Motor Prime from £60,750 to £58,750), which rules nothing out.
        if c.price is not None and left and c.date_kind in ("listed", "seen"):
            priced = [car for car in left if ev.car_prices(car)]
            if len(priced) == len(left) and not any(_band(c.price, ev.car_prices(car)) for car in left):
                vocab = self.vocab.get(c.model or "", set())
                theirs = sorted(car.id for car in (pool or cands) if car not in left and rule_out(c, car, vocab, trims=False) is None
                                and any(abs(p - c.price) <= PRICE_SAME for p in ev.car_prices(car)))
                if theirs:
                    ruled["price"] += len(left)
                    ex["price"] = f"£{c.price:,.0f} is the list price of {theirs[0]}" + (f" and {len(theirs) - 1} more" if len(theirs) > 1 else "")
                    left = []
        return left, ruled, ex

    def place(self, c: Compound, ev: Evidence) -> Link:
        link = self._place(c, ev)
        if link.status != "listed" or not c.model or c.describes == "trim":
            return link
        # Nothing of its own Carwow model fits: the Carwow models Parkers files with it (the Enyaq and the Enyaq vRS, the
        # MG4 and the MG4 XPOWER), if exactly one has a car it can be.
        fits = [(m, l) for m in self.siblings.get(c.model, []) for l in [self._place(replace(c, model=m), ev)]
                if l.status in ("placed", "tied") and l.level in ("car", "version")]
        if len(fits) != 1:
            return link
        m, l = fits[0]
        return replace(l, why=f"nothing of {c.model} fits ({link.why}); of the Carwow models Parkers files with it, only {m} has a car it "
                              f"can be: {l.why}", decided_by=l.decided_by + ("its Parkers model",))

    def _place(self, c: Compound, ev: Evidence) -> Link:
        if c.ignored:
            return Link("ignored", "ignored", why=c.ignored)
        pool = self.pool(c)
        if not pool:
            why = f"no car of its model ({c.model}) is on the master list" if c.model else "its model is not one the catalogue lists"
            return Link("model" if c.model else "none", "listed", why=why)
        exact = [car for car in pool if c.name and c.name in ev.car_names(car)]
        decided: list[str] = []
        left, ruled, ex = self.filter(c, exact, ev, pool) if exact else ([], Counter(), {})
        if left:
            decided.append("the CAP name, exactly as printed")
        else:
            left, ruled, ex = self.filter(c, pool, ev)
        decided += sorted(ruled)
        base = f"{len(left)} of {len(pool)} cars of {c.model} left" + (f": {_ruled_text(ruled, ex)}" if ruled else "")
        if not left:
            return self._none(c, pool, ev, base, ruled)
        if c.describes == "version":
            return self._version(c, left, ev, base, decided, ruled)
        if c.describes == "trim":   # a maker's grade row speaks for every car of its trim and powertrain
            best = _best_spec(left, ev)
            return Link("car", "placed", best.id, tuple(sorted(car.id for car in left if car is not best)), version=best.version,
                        why=base + (f"; it speaks for all {len(left)}" if len(left) > 1 else ""), decided_by=tuple(decided), ruled=dict(ruled))
        if len(left) == 1:
            return Link("car", "placed", left[0].id, version=left[0].version, why=base, decided_by=tuple(decided), ruled=dict(ruled))
        narrowed = left
        if c.price is not None:
            same = [car for car in narrowed if any(abs(p - c.price) <= PRICE_SAME for p in ev.car_prices(car))]
            if same and len(same) < len(narrowed):
                narrowed = same
                decided.append("list price")
                base += f"; its list price £{c.price:,.0f} left {len(same)}"
        if len(narrowed) > 1:
            # Its packs: those it brackets, and a pack of these cars it prints unbracketed (LeaseLoco's 'Premium +')
            named = {p for car in narrowed for p in car.read.packs if set(p.split()) <= set(c.read.words)}
            named = {p for p in named if not any(set(p.split()) < set(q.split()) for q in named)}   # 'premium plus', not 'premium' too
            packs = (c.packs or frozenset()) | named if (c.packs is not None or named) else None
            same = [car for car in narrowed if car.read.packs == packs] if packs is not None else []
            if same and len(same) < len(narrowed):
                narrowed = same
                decided.append("packs")
                base += f"; its packs ({', '.join(sorted(packs)) or 'none'}) left {len(same)}"
        if len(narrowed) == 1:
            return Link("car", "placed", narrowed[0].id, version=narrowed[0].version, why=base, decided_by=tuple(decided), ruled=dict(ruled))
        vs = sorted({car.version for car in narrowed})
        if len(vs) > 1 and not c.names_anything():   # a used card of price and year alone: the best spec of its model says nothing
            return Link("model", "model", why=base + f"; they are {len(vs)} versions and it names no trim or motor, so it stays at its model",
                        decided_by=tuple(decided), ruled=dict(ruled))
        best = _best_spec(narrowed, ev)
        others = tuple(sorted(car.id for car in narrowed if car is not best))
        return Link("car", "tied", best.id, others, version=best.version,
                    why=base + f"; still {len(narrowed)}, so on the best spec of them with the others named", decided_by=tuple(decided),
                    ruled=dict(ruled))

    def _version(self, c: Compound, left: list[Car], ev: Evidence, base: str, decided: list[str], ruled: Counter) -> Link:
        vs = sorted({car.version for car in left})
        if len(vs) == 1:
            return Link("version", "placed", version=vs[0], why=base + f"; one version ({vs[0]})", decided_by=tuple(decided), ruled=dict(ruled))
        if not c.names_anything():
            return Link("model", "model", others=tuple(vs), decided_by=tuple(decided), ruled=dict(ruled),
                        why=base + f"; they are {len(vs)} versions and it names no battery or motor, so it stays at its model")
        # Its range and charging figures are facts of one version: never guessed onto the best spec of several (the best
        # spec rule is for a price).
        return Link("model", "listed", others=tuple(vs), decided_by=tuple(decided), ruled=dict(ruled),
                    why=base + f"; still {len(vs)} versions, so its figures go to none of them")

    def _none(self, c: Compound, pool: list[Car], ev: Evidence, base: str, ruled: Counter) -> Link:
        """None left: the version or model its battery, motor and dates leave, listed."""
        loose = Compound(**{**c.__dict__, "trim": (), "read": Read(), "seats": None, "doors": None, "price": None, "packs": None})
        left, _, _ = self.filter(loose, pool, ev)
        vs = sorted({car.version for car in left})
        if len(vs) == 1:
            return Link("version", "listed", version=vs[0], why=base + f"; it stays at its version ({vs[0]})", ruled=dict(ruled))
        return Link("model", "listed", why=base + (f"; its battery and motor fit {len(vs)} versions, so it stays at its model" if vs else
                                                     "; it stays at its model"), ruled=dict(ruled))


# ---------------------------------------------------------------- reading every record

def _catalogue(conn: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT slug, make, model, make_name, model_name FROM models WHERE electric=1 ORDER BY slug")]


class Models:
    """A record's make and model text → the Carwow catalogue model."""

    def __init__(self, catalogue: list[dict]):
        self.catalogue = catalogue
        self.by_make: dict[str, list[dict]] = {}
        for m in catalogue:
            for k in {normalise.make_key(m["make"]), normalise.make_key(m.get("make_name"))}:
                self.by_make.setdefault(k, []).append(m)
        self.cache: dict[tuple, str | None] = {}

    def of(self, make: str | None, model: str | None) -> str | None:
        k = (make or "", model or "")
        if k not in self.cache:
            self.cache[k] = self._of(make or "", model or "")
        return self.cache[k]

    def _of(self, make: str, model: str) -> str | None:
        pool = self.by_make.get(normalise.make_key(make)) or []
        if not pool or not model:
            return None
        model = re.sub(rf"^{re.escape(make)}\s+", "", model, flags=re.I)
        hit = match_model(make, model, pool)
        if hit:
            return hit["slug"]
        as_car = [(m, {"model": m.get("model_name") or m["model"], "model_slug": m["model"]}) for m in pool]
        for found in ([m for m, c in as_car if gold.model_is(model, c, make)], [m for m, c in as_car if gold.model_agrees(model, c)]):
            if len(found) == 1:
                return found[0]["slug"]
        return None

    def evdb(self, make: str | None, model: str | None) -> str | None:
        pool = self.by_make.get(normalise.make_key(make)) or []
        m = facts.model_of(make or "", model or "", pool)
        return m["slug"] if m else None


def _latest_offers(conn: sqlite3.Connection) -> dict[str, tuple[str, str, dict]]:
    """Offer key → (source, last seen, the record as last read): ties at one instant by content."""
    out: dict[str, tuple] = {}
    for src, key, last, fp, row in conn.execute("SELECT source, record_key, last_seen_at, fingerprint, row FROM records WHERE kind='offer'"):
        rank = (last, fp, src, row)
        if key not in out or rank > out[key][0]:
            out[key] = (rank, src, last, row)
    return {k: (v[1], v[2], json.loads(v[3])) for k, v in out.items()}


def _today_offers(conn: sqlite3.Connection) -> dict[str, str]:
    out: dict[str, tuple] = {}
    for key, car, at in conn.execute("SELECT offer_key, car_id, observed_at FROM offer_observations ORDER BY offer_key, observed_at, car_id"):
        if key not in out or (at, car) > (out[key][1], out[key][0]):
            out[key] = (car, at)
    return {k: v[0] for k, v in out.items()}


def compounds(conn: sqlite3.Connection, today_facts: dict[tuple[str, str], tuple[str, ...]] | None = None) -> tuple[list[Compound], dict[str, dict]]:
    """Every record that names a car, as compounds; and, per CAP id, what Carwow's own records say of its derivative."""
    models = Models(_catalogue(conn))
    today_facts = today_facts or {}
    cars_today = {r[0] for r in conn.execute("SELECT id FROM cars")}
    out: list[Compound] = []
    derivs: dict[str, dict] = {}    # cap id → the details its Carwow records give, merged

    def describe(cap: str, field: str, value, rank: tuple = ()) -> None:
        if value in (None, "", [], ()):
            return
        d = derivs.setdefault(cap, {})
        d.setdefault(field, []).append((rank, value))

    def today_cap(cap: str | None) -> tuple[str, ...]:
        return (f"carwow-cap:{cap}",) if cap and f"carwow-cap:{cap}" in cars_today else ()

    # The registry: every derivative on Carwow's model pages.
    for r in conn.execute("SELECT cap_id, make_slug, model_slug, name, trim, engine, rrp, version_date, last_seen_at, payload FROM derivatives ORDER BY cap_id"):
        p = json.loads(r["payload"])
        slug = f"{r['make_slug']}/{r['model_slug']}"
        cap = r["cap_id"]
        for f, v in (("model", slug), ("make", p.get("make") or r["make_slug"]), ("name", r["name"]), ("trim", r["trim"]),
                     ("engine", r["engine"]), ("price", r["rrp"]), ("date", r["version_date"]), ("seen", r["last_seen_at"])):
            describe(cap, f, v, (3, r["version_date"] or ""))
        out.append(compound("carwow_model", "registry", cap, f"{r['name']}", make=p.get("make") or r["make_slug"], model=slug, cap=cap,
                            label=f"{p.get('make') or r['make_slug']} {p.get('model') or r['model_slug']} {r['name']}",
                            name=r["name"], price=r["rrp"], date=r["version_date"], date_kind="listed", today=today_cap(cap)))
    # Specification rows: Carwow's, by CAP id; NCD's technical table, by CAP id; the makers' grade tables; EV Database.
    evdb_pages: dict[str, dict] = {}
    for key, payload in conn.execute("SELECT spec_key, payload FROM specs WHERE source='evdb_cars'"):
        evdb_pages[key.split(":", 1)[1]] = json.loads(payload)
    spec_today = {r[0]: r[1] for r in conn.execute("SELECT spec_key, car_id FROM specs WHERE car_id IS NOT NULL")}
    for key, source, last_seen, payload in conn.execute("SELECT spec_key, source, last_seen_at, payload FROM specs WHERE source IN "
                                             "('carwow_specs','ncd','kia_specs','hyundai_specs','evdb','evdb_cars') ORDER BY spec_key"):
        p = json.loads(payload)
        n = p.get("numbers") or {}
        if source == "carwow_specs" and p.get("cap_id"):
            cap, slug = p["cap_id"], f"{p.get('make_slug')}/{p.get('model_slug')}"
            for f, v in (("model", slug), ("make", p.get("make")), ("trim", p.get("trim")), ("engine", p.get("engine")),
                         ("price", p.get("rrp")), ("date", p.get("version_date")), ("drive", drive_field(n.get("drive"))),
                         ("doors", n.get("doors")), ("kwh", n.get("battery_kwh")), ("seen", last_seen)):
                describe(cap, f, v, (2, p.get("version_date") or ""))
            out.append(compound(source, "spec", key, f"{p.get('trim') or ''} {p.get('engine') or ''}", make=p.get("make"), model=slug, cap=cap,
                                label=p.get("variant") or key, trim=p.get("trim"), price=p.get("rrp"), date=p.get("version_date"),
                                date_kind="listed", drive=drive_field(n.get("drive")), doors=n.get("doors"),
                                today=(spec_today[key],) if key in spec_today else ()))
        elif source == "ncd" and p.get("cap_id"):
            out.append(compound(source, "spec", key, p.get("variant") or "", make=p.get("make"), model=None, cap=p["cap_id"],
                                label=p.get("variant") or key, today=(spec_today[key],) if key in spec_today else ()))
        elif source in ("kia_specs", "hyundai_specs"):
            kwhs = [n.get("battery_kwh")] if n.get("battery_kwh") else list(p.get("batteries") or [])
            text = p.get("variant") or f"{p.get('model') or ''} {p.get('trim') or ''}"
            out.append(compound(source, "spec", key, re.sub(re.escape(p.get("trim") or "") + r"\s*", " ", text, count=1) if p.get("trim") else text,
                                make=p.get("make"), model=models.of(p.get("make"), p.get("model")), label=text, trim=p.get("trim"),
                                kwh=kwhs[0] if len(kwhs) == 1 else None, drive=drive_field(n.get("drive")) if isinstance(n.get("drive"), str) else None,
                                date=p.get("observed_at"), date_kind="seen", describes="trim", today=today_facts.get((source, key), ())))
        elif source in ("evdb", "evdb_cars"):
            vid = key.split(":", 1)[1]
            card_n = n if source == "evdb" else {}
            page_n = (evdb_pages.get(vid) or {}).get("numbers") or {} if source == "evdb" else n
            nums = {**card_n, **page_n}
            since = _months(nums.get("on_sale_since")) or (int(nums["year_from"]) * 12 if _num(nums.get("year_from")) else None)
            until = _months(nums.get("on_sale_until"))
            if until is None and nums.get("on_sale") is False and since is not None:
                until = since + 12
            out.append(compound(source, "variant", key, p.get("model") or "", make=p.get("make"), model=models.evdb(p.get("make"), p.get("model")),
                                label=f"{p.get('make')} {p.get('model')}", kw=nums.get("power_kw"), usable=nums.get("battery_usable_kwh"),
                                drive=drive_field(nums.get("drive")) if nums.get("drive") else None, seats=nums.get("seats"),
                                span=(since, until) if since is not None or until is not None else None, date_kind="span",
                                describes="version", today=today_facts.get(("evdb", f"evdb:{vid}"), ())))
    # The makers' configurators.
    for r in conn.execute("SELECT fsc, make_slug, model_slug, trim, battery_kwh, price, payload FROM configurations ORDER BY fsc"):
        p = json.loads(r["payload"])
        packs = frozenset(t for pk in p.get("packages") or [] for t in pack_tokens(pk.get("name"), p.get("make")))
        out.append(compound("hyundai_configurator", "configuration", r["fsc"], p.get("powertrain") or "", make=p.get("make") or r["make_slug"],
                            model=f"{r['make_slug']}/{r['model_slug']}", label=f"{p.get('model')} {r['trim']} {p.get('powertrain') or ''} £{r['price'] or 0:,.0f}",
                            trim=r["trim"], kwh=r["battery_kwh"], drive=drive_field(p.get("drive")), seats=p.get("seats"), price=r["price"],
                            packs=packs, date=p.get("observed_at"), date_kind="seen",
                            today=today_facts.get(("hyundai_configurator", r["fsc"]), ())))
    # Carwow's configurator pages, by CAP id.
    for (cap,) in conn.execute("SELECT cap_id FROM options ORDER BY cap_id"):
        out.append(compound("carwow_options", "options", cap, "", make=None, model=None, cap=cap, label=f"Carwow configurator {cap}", today=today_cap(cap)))
    # Offers: each offer's latest record.
    today_off = _today_offers(conn)
    stubs: dict[str, tuple] = {}
    for okey, (src, last, row) in sorted(_latest_offers(conn).items()):
        ref = row.get("car_ref") or {}
        if not ref:
            continue
        today = (today_off[okey],) if okey in today_off else ()
        seen = row.get("observed_at") or last
        if ref.get("source") == "carwow-cap" and ref.get("key"):
            cap = str(ref["key"])
            stub = ref.get("stub")
            if stub:
                rank = (stub.get("version_date") or "", last, json.dumps(stub, sort_keys=True))
                if cap not in stubs or rank > stubs[cap][0]:
                    stubs[cap] = (rank, stub)
                describe(cap, "seen", last, (1, last))
            text = ref.get("derivative") or ""
            name = text if ref.get("derivative") and read(text).cap_style else None
            if name:
                describe(cap, "name_seen", name, (1, last))
            out.append(compound(src, "offer", okey, text, make=ref.get("make"), model=None, cap=cap, label=ref.get("label") or okey,
                                name=name, price=ref.get("rrp"), date=seen, date_kind="seen", today=today))
            continue
        text = ref.get("derivative") or ref.get("label") or ""
        model = models.of(ref.get("make"), ref.get("model"))
        out.append(compound(src, "offer", okey, text, make=ref.get("make"), model=model, label=ref.get("label") or okey,
                            name=re.sub(r" \[\d seat\]$", "", text) if text else None, price=ref.get("rrp"), date=seen, date_kind="seen", today=today))
    for cap, (_, stub) in sorted(stubs.items()):
        slug = f"{stub.get('make_slug')}/{stub.get('model_slug')}"
        for f, v in (("model", slug), ("make", stub.get("make")), ("trim", stub.get("trim")), ("engine", stub.get("engine")),
                     ("price", stub.get("rrp")), ("date", stub.get("version_date"))):
            describe(cap, f, v, (1, stub.get("version_date") or ""))
    # Used cars.
    for r in conn.execute("SELECT listing_key, source, make_slug, model_slug, year, car_id, payload FROM used_listings ORDER BY listing_key"):
        p = json.loads(r["payload"])
        ref = p.get("car_ref") or {}
        text = ref.get("derivative") or p.get("derivative") or ""
        fuel = normalise.fold(p.get("fuel"))
        out.append(compound(r["source"], "used", r["listing_key"], text, make=ref.get("make") or p.get("make") or r["make_slug"],
                            model=f"{r['make_slug']}/{r['model_slug']}" if r["make_slug"] and r["model_slug"] else None,
                            label=f"{p.get('make') or ''} {p.get('model') or ''} {text} ({r['year'] or '?'})".strip(),
                            name=text or None, trim=p.get("trim"), seats=p.get("seats"), doors=p.get("doors"),
                            drive=drive_field(p.get("drive")), rex=(True if "range extender" in fuel else False if fuel == "electric" else None),
                            price=p.get("list_price_when_new"), date=f"{int(r['year']):04d}-06" if _num(r["year"]) else None, date_kind="registered",
                            today=(r["car_id"],) if r["car_id"] else today_facts.get((r["source"], r["listing_key"]), ())))
    return out, derivs


def _one(d: dict, f: str):
    """What Carwow's records say of a detail: the registry's, then the specification row's, then the deals card's (the
    latest price list's of each)."""
    vals = d.get(f) or []
    return max(vals, key=lambda rv: (rv[0], json.dumps(rv[1], sort_keys=True)))[1] if vals else None


def derivative_compound(cap: str, d: dict, today: tuple[str, ...]) -> Compound:
    """What every Carwow record of one CAP id says of its derivative, as one compound."""
    name = _one(d, "name")
    seen_names = Counter(v for _, v in d.get("name_seen") or [])
    if not name and seen_names:
        name = sorted(seen_names.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]   # the CAP-style name brokers print for the id
    trim, engine = _one(d, "trim"), _one(d, "engine")
    text = name or f"{trim or ''} {engine or ''}"
    c = compound("carwow", "derivative", cap, text, make=_one(d, "make"), model=_one(d, "model"), cap=cap, name=name, trim=trim,
                 kwh=None, drive=_one(d, "drive"), doors=_one(d, "doors"), price=_one(d, "price"), date=_one(d, "date") or _one(d, "seen"),
                 date_kind="listed", today=today, label=f"{_one(d, 'make') or ''} {text}")
    c.extra = {"named": bool(name), "engine": engine, "seen": _one(d, "seen")}
    if combustion(f"{trim or ''} {engine or ''} {name or ''}"):
        c.ignored = "its engine burns fuel"
    return c


# ---------------------------------------------------------------- the run

@dataclass
class Result:
    cars: dict[str, Car]
    links: dict[tuple[str, str], Link]          # (source, record key) → its link
    compounds: dict[tuple[str, str], Compound]
    derivatives: dict[str, Link]                # CAP id → its derivative's link
    derivs: dict[str, Compound]                 # CAP id → what Carwow's records say of its derivative
    rounds: int
    converged: bool


def _model_pools(cars: dict[str, Car], mapping: list[dict]) -> tuple[dict[str, list[str]], dict[str, set[str]]]:
    """Carwow model → the ids of the cars its records are filtered against, and the trim words of those cars."""
    by_gen: dict[tuple[str, str], list[str]] = {}
    for car in cars.values():
        if car.source == "parkers":
            by_gen.setdefault((f"{car.make}/{car.model}", car.generation), []).append(car.id)
    pools: dict[str, set[str]] = {}
    of_gen: dict[tuple[str, str], set[str]] = {}   # (Parkers model, generation) → the Carwow models it is filed under
    for r in mapping:
        if r.get("parkers"):
            for g in r.get("generations") or []:
                of_gen.setdefault((r["parkers"], g["generation"]), set()).add(r["slug"])
                for cid in by_gen.get((r["parkers"], g["generation"]), []):
                    pools.setdefault(r["slug"], set()).add(cid)
                    cars[cid].carwow_models.add(r["slug"])
    # A car made from Carwow alone is a car of its Parkers generation, so of every Carwow model filed under it (the
    # Enyaq vRS's leases name the Enyaq).
    for car in cars.values():
        if car.source == "carwow":
            for m in car.carwow_models | of_gen.get((f"{car.make}/{car.model}", car.generation), set()):
                pools.setdefault(m, set()).add(car.id)
    # A trim's words count only as its cars' names print them: Carwow calls the iX3's plain trim 'Standard', which no
    # CAP name prints.
    vocab = {m: {w for cid in ids for w in cars[cid].trim if w in cars[cid].words} for m, ids in pools.items()}
    return {m: sorted(ids) for m, ids in pools.items()}, vocab


def carwow_vocab(derivs: dict[str, Compound]) -> dict[str, set[str]]:
    """The trim words Carwow's derivatives print in their own CAP names, per Carwow model: a trim Parkers does not list
    ('GT+', 'Engage+', 'Premium+') still tells a derivative from the trim without it. Its trim field's words count only
    where its name prints them (Carwow calls the iX3's plain trim 'Standard', which no name prints)."""
    out: dict[str, set[str]] = {}
    for c in derivs.values():
        if c.model and c.trim and c.name and not c.ignored:
            out.setdefault(c.model, set()).update(set(c.trim) & set(read(c.name, c.make).words))
    return out


def _with(vocab: dict[str, set[str]], *more: dict[str, set[str]]) -> dict[str, set[str]]:
    out = {m: set(ws) for m, ws in vocab.items()}
    for extra in more:
        for m, ws in extra.items():
            out.setdefault(m, set()).update(ws)
    return out


def siblings_of(mapping: list[dict]) -> dict[str, list[str]]:
    """Carwow model → the other Carwow models placed on the same Parkers model."""
    by: dict[str, list[str]] = {}
    for r in sorted(mapping, key=lambda r: r["slug"]):
        if r.get("parkers"):
            by.setdefault(r["parkers"], []).append(r["slug"])
    return {s: [o for o in group if o != s] for group in by.values() for s in group if len(group) > 1}


def _generation_for(r: dict | None, date: int | None) -> str:
    """The generation of a Carwow model a derivative of it is in: of those on sale at its price list's date, the latest."""
    gens = (r or {}).get("generations") or []
    if not gens:
        return ""
    def on(g: dict) -> bool:
        s, u = _months(g.get("since")), _months(g.get("until"))
        return date is None or ((s is None or s <= date + LISTED_BEFORE) and (u is None or u >= date - LISTED_AFTER))
    fit = [g for g in gens if on(g)] or gens
    return max(fit, key=lambda g: (g.get("start") or 0, g["generation"]))["generation"]


def carwow_car(c: Compound, r: dict | None) -> Car:
    """A Carwow derivative no Parkers entry can be, as a car of the Parkers model and generation its model maps to."""
    make, model = (r["parkers"].split("/", 1) if r and r.get("parkers") else (c.model or "-/-").split("/", 1))
    gen = _generation_for(r, c.date) if r and r.get("parkers") else ""
    rd = c.read
    named = c.extra.get("named")
    trim = c.trim
    if c.name:   # the trim as its CAP name prints it
        name_words = set(read(c.name, c.make).words)
        trim = tuple(w for w in trim if w in name_words)
    cid = car_key(make, model, gen, trim, Read(**{**rd.__dict__, "kw": c.kw, "kwh": c.kwh, "doors": c.doors}),
                  price=None if named or rd.packs else c.price)
    seen = _months(c.extra.get("seen"))
    return Car(cid, make, model, gen, "carwow", trim, rd, kw=c.kw, kwh=c.kwh, doors=c.doors, seats=c.seats, drive=c.drive,
               since=c.date, until=seen, open=True, names={c.name} if c.name else set(), words=set(rd.words) | {w for p in rd.packs for w in p.split()},
               prices={c.price} if c.price else set(), keys={f"carwow-cap:{c.key}"}, carwow_models={c.model} if c.model else set())


def resolve(parkers: dict[str, Car], comps: list[Compound], derivs: dict[str, Compound], mapping: list[dict]) -> Result:
    """The links of every compound: CAP ids' derivatives first, round by round, then every record."""
    by_slug = {r["slug"]: r for r in mapping}
    sib = siblings_of(mapping)
    extra = carwow_vocab(derivs)
    # The trim words that decide which derivatives become cars must be those the final pass reads, which those cars add
    # to: so the passes repeat, with the words found so far, until they are the same (they only grow, so they stop).
    floor: dict[str, set[str]] = {}
    for _ in range(MAX_ROUNDS):
        cars, made_why, pools, vocab, final = _cars_and_vocab(parkers, derivs, mapping, by_slug, sib, _with(extra, floor))
        if final == vocab:
            break
        floor = final
    res = Resolver(cars, pools, final, sib)
    # Rounds: a CAP id placed on one car gives it Carwow's name and price, which the next round reads.
    ev, used, prev, rounds, converged = Evidence(), Evidence(), None, 0, False
    dlinks: dict[str, Link] = {}
    while rounds < MAX_ROUNDS:
        rounds += 1
        used = ev
        dlinks = {cap: res.place(derivs[cap], used) for cap in sorted(derivs)}
        sig = {cap: (l.car, l.others, l.status) for cap, l in dlinks.items()}
        nxt = Evidence()
        for cap, l in sorted(dlinks.items()):
            c = derivs[cap]
            if l.status in ("placed", "new car") and l.level == "car" and l.car:
                if c.name:
                    nxt.names.setdefault(l.car, set()).add(c.name)
                if c.price:
                    nxt.prices.setdefault(l.car, set()).add(c.price)
                nxt.caps.setdefault(l.car, set()).add(cap)
        if sig == prev:
            converged = True
            break
        prev, ev = sig, nxt
    for cap, l in dlinks.items():
        if l.car and l.level == "car" and cars[l.car].source == "carwow" and f"carwow-cap:{cap}" in cars[l.car].keys:
            dlinks[cap] = Link("car", "new car", l.car, l.others, version=l.version, decided_by=l.decided_by, ruled=l.ruled,
                               why=f"no Parkers car can be it ({made_why[cap]}), so it is a car of its own" + (
                                   f"; {l.why.split('; ', 1)[1]}" if l.status == "tied" and "; " in l.why else ""))
    links: dict[tuple[str, str], Link] = {}
    comp: dict[tuple[str, str], Compound] = {}
    for c in sorted(comps, key=lambda c: (c.source, c.key)):
        k = (c.source, c.key)
        comp[k] = c
        links[k] = follow(res, c, dlinks.get(c.cap), derivs.get(c.cap), used) if c.cap else res.place(c, used)   # the state the CAP ids were placed in
    return Result(cars, links, comp, dlinks, derivs, rounds, converged)


def _cars_and_vocab(parkers: dict[str, Car], derivs: dict[str, Compound], mapping: list[dict], by_slug: dict[str, dict],
                    sib: dict[str, list[str]], floor: dict[str, set[str]]):
    """The master list with the Carwow derivatives no Parkers car can be, read with the trim words `floor` adds: the
    cars, why each Carwow one was made, and the pools and trim words before and after the Carwow cars join."""
    cars = {cid: Car(**{**car.__dict__, "names": set(car.names), "words": set(car.words), "prices": set(car.prices),
                        "keys": set(car.keys), "carwow_models": set()}) for cid, car in parkers.items()}
    pools, vocab = _model_pools(cars, mapping)
    vocab = _with(vocab, floor)
    for car in cars.values():
        car.version = version_of(car)
    # Carwow derivatives no Parkers entry can be become cars.
    first = Resolver(cars, pools, vocab, sib)
    made: dict[str, Car] = {}
    made_why: dict[str, str] = {}
    for cap in sorted(derivs):
        c = derivs[cap]
        if c.ignored or not c.model:
            continue
        link = first.place(c, Evidence())
        if link.status != "listed":   # placed on a Parkers car, or its details fit several and tell them apart from none
            continue
        if not (c.trim and (c.kw or c.kwh or c.drive)):   # its own trim and motor (a Tesla's names print only its drive)
            continue
        made_why[cap] = link.why
        car = carwow_car(c, by_slug.get(c.model))
        if car.id in made:
            m = made[car.id]
            m.names |= car.names
            m.prices |= car.prices
            m.keys |= car.keys
            m.carwow_models |= car.carwow_models
            m.words |= car.words
            m.since = min((x for x in (m.since, car.since) if x is not None), default=None)
            m.until = max((x for x in (m.until, car.until) if x is not None), default=None)
        else:
            made[car.id] = car
    for cid, car in made.items():
        if cid in cars:   # the details of a Parkers car its dates ruled it out of (a price list after Parkers' last): its dates tell them apart
            car = Car(**{**car.__dict__, "id": f"{cid}-from-{_ym(car.since) or 'carwow'}"})
        car.version = version_of(car)
        cars[car.id] = car
    final_pools, final = _model_pools(cars, mapping)
    return cars, made_why, final_pools, vocab, _with(final, floor)


def follow(res: Resolver, c: Compound, dlink: Link | None, d: Compound | None, ev: Evidence) -> Link:
    """A record printing a CAP id goes where the id's derivative went, unless one of its own details contradicts that car."""
    if c.ignored:
        return Link("ignored", "ignored", why=c.ignored)
    if dlink is None or d is None:
        return Link("none", "listed", why=f"no Carwow record describes CAP id {c.cap}")
    if dlink.status == "ignored":
        return Link("ignored", "ignored", why=f"CAP id {c.cap}: {dlink.why}")
    if not dlink.car:
        return Link(dlink.level, "listed", version=dlink.version, why=f"its CAP id {c.cap} is not placed: {dlink.why}")
    car = res.cars[dlink.car]
    vocab = res.vocab.get(d.model or "", set())
    r = rule_out(c, car, vocab, dates=c.date_kind != "seen")   # its CAP id names the car outright: an offer seen now may be run-out stock
    if r:
        return Link("none", "contradicts", why=f"its CAP id {c.cap} is {car.id}, but its {r[0]} contradicts it ({r[1]})")
    return Link(dlink.level, dlink.status if dlink.status != "new car" else "placed", dlink.car, dlink.others, version=dlink.version,
                why=f"its CAP id {c.cap}: " + dlink.why, decided_by=("CAP id",) + tuple(dlink.decided_by), ruled=dlink.ruled)


# ---------------------------------------------------------------- today's lookups, and the comparison

def today_facts(conn: sqlite3.Connection) -> dict[tuple[str, str], tuple[str, ...]]:
    """Today's cars of the records the snapshot lays over cars rather than matching (services/claims.py), by the same
    functions it uses: an EV Database variant's (facts.pick_variant, by each car's battery and year), a maker's
    configuration's (claims.from_configurations: trim, battery and price, then brackets) and a maker's grade row's
    (every car of its trim). The claim store resolves each car's battery from every source; here it is the car's own
    figure or the one its engine prints, which is the same figure for every car with a Carwow specification row."""
    out: dict[tuple[str, str], tuple[str, ...]] = {}
    cars = [json.loads(p) for (p,) in conn.execute("SELECT payload FROM cars ORDER BY id")]
    by_trim: dict[str, list[str]] = {}
    for c in cars:
        by_trim.setdefault(claims.trim_subject(c.get("make"), c.get("model"), c.get("trim")), []).append(c["id"])
    for key, source, payload in conn.execute("SELECT spec_key, source, payload FROM specs WHERE source IN ('kia_specs','hyundai_specs')"):
        p = json.loads(payload)
        out[(source, key)] = tuple(sorted(by_trim.get(claims.trim_subject(p.get("make"), p.get("model"), p.get("trim")), [])))
    derivs = [json.loads(p) for (p,) in conn.execute("SELECT payload FROM derivatives ORDER BY cap_id")]
    rows = [json.loads(p) for (p,) in conn.execute("SELECT payload FROM configurations ORDER BY make_slug, model_slug, fsc")]
    store = claims.Store()
    claims.from_configurations(store, rows, derivs)
    for cap, fsc in store.configured.items():
        out[("hyundai_configurator", fsc)] = (f"carwow-cap:{cap}",)
    catalogue = _catalogue(conn)
    models = Models(catalogue)
    pages = {k.split(":", 1)[1]: json.loads(p) for k, p in conn.execute("SELECT spec_key, payload FROM specs WHERE source='evdb_cars'")}
    variants: dict[str, list[dict]] = {}
    for key, payload in conn.execute("SELECT spec_key, payload FROM specs WHERE source='evdb' ORDER BY spec_key"):
        r = json.loads(payload)
        slug = models.evdb(r.get("make"), r.get("model"))
        m = next((x for x in catalogue if x["slug"] == slug), None) if slug else None
        if not m:
            continue
        page = pages.get(key.split(":", 1)[1])
        if page:
            r["numbers"] = {**(r.get("numbers") or {}), **(page.get("numbers") or {})}
        variants.setdefault(claims.model_key(m.get("make_name") or m["make"], m.get("model_name") or m["model"]), []).append(r)
    picked: dict[str, list[str]] = {}
    since: dict[str, str] = {}
    for c in cars:
        vs = variants.get(claims.model_key(c.get("make"), c.get("model")))
        if not vs:
            continue
        kwh = c.get("battery_kwh") or normalise.kwh(f"{c.get('variant') or ''} {c.get('trim') or ''}")
        v = facts.pick_variant({**c, "battery_kwh": kwh}, vs)
        if v:
            picked.setdefault(v["spec_key"], []).append(c["id"])
            if (v.get("numbers") or {}).get("on_sale_since"):
                since[c["id"]] = v["numbers"]["on_sale_since"]
    for key, ids in picked.items():
        out[("evdb", key)] = tuple(sorted(ids))
    # A used car the matching tied to no derivative counts, in the snapshot, as every car of the trim and battery its
    # text names (snapshot.used_key_for_text), unless registered before that version went on sale.
    by_model: dict[str, list[dict]] = {}
    for c in cars:
        mk = f"{(c.get('make_slug') or '').lower()}/{c.get('model_slug') or ''}"
        c2 = {**c, "on_sale_since": since.get(c["id"])}
        c2["used_key"] = snapshot.used_key(c2, mk)
        if c2["used_key"]:
            by_model.setdefault(mk, []).append(c2)
    for key, source, mk, md, year, payload in conn.execute(
            "SELECT listing_key, source, make_slug, model_slug, year, payload FROM used_listings WHERE car_id IS NULL"):
        text = json.loads(payload).get("derivative")
        pool = by_model.get(f"{(mk or '').lower()}/{md or ''}", [])
        k = snapshot.used_key_for_text(text, pool, year) if text and pool else None
        if k:
            out[(source, key)] = tuple(sorted(c["id"] for c in pool if c["used_key"] == k))
    return out


OUTCOMES = ("same", "merged", "to best spec", "moved", "newly placed", "lost", "unplaced")


@dataclass
class Compared:
    outcome: str
    today: tuple[str, ...]           # today's cars, as the current lookups name them (carwow-cap:<id>)
    today_as: tuple[str, ...]        # those cars as the resolver's: the car each CAP id's derivative went to
    resolver: tuple[str, ...]
    listed: bool


def versions(res: Result) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for car in sorted(res.cars.values(), key=lambda c: c.id):
        out.setdefault(car.version, []).append(car.id)
    return out


def compare(res: Result) -> dict[tuple[str, str], Compared]:
    """Every record's car today against the resolver's: same, moved, newly placed, lost, or unplaced by both. Today's
    car is a CAP id's derivative, read as the resolver's car that CAP id went to. A record that describes a version or
    a trim is compared by every car it reaches."""
    as_car = {f"carwow-cap:{cap}": l.car for cap, l in res.derivatives.items() if l.car and l.level == "car"}
    vs = versions(res)
    out = {}
    for k, link in res.links.items():
        c = res.compounds[k]
        whole = c.describes != "car"
        listed = link.status in ("listed", "contradicts")   # a version it stays at is not a placement
        mine = () if listed else tuple(sorted(set(link.cars(vs)))) if whole else ((link.car,) if link.car else ())
        today_as = tuple(sorted({as_car.get(t) or f"({t})" for t in c.today}))
        if not c.today and not mine:
            outcome = "unplaced"
        elif not c.today:
            outcome = "newly placed"
        elif not mine:
            outcome = "lost"
        elif whole:
            outcome = "same" if set(today_as) == set(mine) else "moved"
        elif mine[0] in today_as:   # today's car, or one of the cars of the trim and battery a used car's text names
            outcome = "same"
        else:   # today's car is one the resolver names beside the best spec it chose (BOARD.md, T7), or another
            outcome = "to best spec" if set(today_as) & set(link.others) else "moved"
        out[k] = Compared(outcome, c.today, today_as, mine, link.status in ("listed", "contradicts"))
    # Reading today's cars through the resolver's own placement hides two of today's cars made one: a record that keeps
    # its car is 'merged' when its resolver car holds records of another of today's cars. (One of today's cars made two
    # shows already, as the records that moved.)
    held: dict[str, set[str]] = {}    # resolver car → today's cars of its records
    for k, cm in out.items():
        if len(cm.today) == 1 and len(cm.resolver) == 1 and res.compounds[k].describes == "car":
            held.setdefault(cm.resolver[0], set()).add(cm.today[0])
    for k, cm in out.items():
        if cm.outcome == "same" and len(cm.today) == 1 and len(cm.resolver) == 1 and len(held.get(cm.resolver[0], ())) > 1:
            cm.outcome = "merged"
    return out


# ---------------------------------------------------------------- the build's step

def run(conn: sqlite3.Connection) -> dict:
    """The resolver over every record the build wrote: its cars into `resolver_cars`, every record's link and its
    comparison with today's into `resolver_links`; returns the summary the build's report prints."""
    mapping = model_map.load(conn)
    parkers, _ = master_list(conn)
    comps, raw = compounds(conn, today_facts(conn))
    cars_today = {r[0] for r in conn.execute("SELECT id FROM cars")}
    derivs = {cap: derivative_compound(cap, d, (f"carwow-cap:{cap}",) if f"carwow-cap:{cap}" in cars_today else ())
              for cap, d in raw.items()}
    res = resolve(parkers, comps, derivs, mapping)
    cmp = compare(res)
    write(conn, res, cmp)
    return summary(res, cmp)


def summary(res: Result, cmp: dict[tuple[str, str], Compared]) -> dict:
    by_source: dict[str, Counter] = {}
    for (src, key), c in cmp.items():
        t = by_source.setdefault(src, Counter())
        t[c.outcome] += 1
        t["listed"] += int(c.listed)
        t["at model"] += int(res.links[(src, key)].status == "model")
    cars = list(res.cars.values())
    vs = versions(res)
    reached = {x for l in res.links.values() if l.status not in ("listed", "contradicts") for x in l.cars(vs)}
    return {"cars": len(cars), "parkers": sum(c.source == "parkers" for c in cars), "carwow": sum(c.source == "carwow" for c in cars),
            "off_sale": sum(not c.open for c in cars), "with_records": len(reached & set(res.cars)), "versions": len(vs),
            "rounds": res.rounds, "converged": res.converged,
            "derivatives": dict(sorted(Counter(l.status for l in res.derivatives.values()).items())),
            "by_source": {s: {k: t.get(k, 0) for k in (*OUTCOMES, "listed", "at model")} for s, t in sorted(by_source.items())}}


def report_lines(s: dict) -> list[str]:
    """The build report's summary of the resolver (pipeline/build.py)."""
    d = s["derivatives"]
    out = [f"resolver: {s['cars']} cars ({s['parkers']} from Parkers, {s['carwow']} from Carwow alone; {s['off_sale']} no longer on sale), "
           f"{s['versions']} versions; Carwow's CAP ids: " + ", ".join(f"{n} {k}" for k, n in d.items())
           + f"; {s['rounds']} rounds" + ("" if s["converged"] else " (stopped before it settled)")]
    out.append("resolver against today's lookups, by source: " + " / ".join("unplaced by both" if k == "unplaced" else k for k in OUTCOMES)
               + "; listed; left at their model")
    for src, t in s["by_source"].items():
        out.append(f"  {src}: " + " / ".join(str(t[k]) for k in OUTCOMES) + f"; {t['listed']}; {t['at model']}")
    return out


def write(conn: sqlite3.Connection, res: Result, cmp: dict[tuple[str, str], Compared]) -> None:
    conn.execute("DELETE FROM resolver_cars")
    conn.execute("DELETE FROM resolver_links")
    conn.executemany("INSERT INTO resolver_cars (id, source, make, model, generation, version, on_sale, payload) VALUES (?,?,?,?,?,?,?,?)",
                     [(c.id, c.source, c.make, c.model, c.generation, c.version, int(c.open), json.dumps(c.row(), ensure_ascii=False, sort_keys=True))
                      for c in sorted(res.cars.values(), key=lambda c: c.id)])
    rows = []
    for cap, l in sorted(res.derivatives.items()):
        rows.append(("carwow", "derivative", cap, res.derivs[cap], l, None))
    for k, l in sorted(res.links.items()):
        rows.append((k[0], res.compounds[k].kind, k[1], res.compounds[k], l, cmp.get(k)))
    out = []
    for src, kind, key, c, l, cm in rows:
        payload = {"label": c.label if c else None, "details": c.details() if c else None, **l.row(),
                   **({"today": list(cm.today), "today_as": list(cm.today_as), "resolver": list(cm.resolver)} if cm else {})}
        out.append((src, kind, key, c.model if c else None, l.level, l.status, l.car, l.version, cm.outcome if cm else None,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True)))
    conn.executemany("INSERT INTO resolver_links (source, kind, record_key, model, level, status, car_id, version, outcome, payload) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?)", out)
