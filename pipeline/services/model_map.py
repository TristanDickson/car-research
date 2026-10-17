"""Carwow's catalogue models mapped to Parkers' models and generations (BOARD.md, T2), derived by every build
from the records: the resolver (docs/ARCHITECTURE-NEXT.md) filters a record against the derivatives of its own
model, and every source but Parkers names a model as Carwow's catalogue does.

Parkers files body styles and some versions as generations of one model ('q4-e-tron/sportback-2021',
'ioniq-5/n-2023'), each labelled with its body or version and its start year; Carwow gives them models of
their own ('Q4 Sportback e-tron', 'Ioniq 5 N'). The rules, strongest first:

  1. The Parkers model.  Of the Parkers models of the same make whose name reads like Carwow's model's
     (_closeness, once the words naming one of that Parkers model's generations and the words that only say
     'electric' are set aside), the one whose derivatives share the most names with Carwow's registry of the
     model: exactly as printed, then read alike (normalise.name_compact). Then the closer name; then the years
     (a Parkers model none of whose generations was on sale over the months Carwow's price lists are dated loses
     a tie). Rule 'name and derivatives' when names are shared, 'name' when none are.
     When no Parkers model's name reads alike: the one Parkers model holding every name on the registry
     ('derivatives'). Fewer is listed: Parkers files the Ioniq 3's first derivatives under the Ioniq 5 N.
     Still tied: ambiguous, listed with the candidates. None: unplaced, listed.
  2. The generations.  Those whose label Carwow's model name prints ('Sportback', 'N', 'Touring'); else those
     no other Carwow model placed on the same Parkers model claims by its name, less any whose derivatives
     share names only with another such model while this one shares names with a generation of its own; else
     those sharing names with this one; else every one, and the model is listed as ambiguous. Carwow's model
     spans every generation left (the resolver tells them apart by dates).

Nothing is typed in by hand, and no answer depends on the order records were read: every choice is a maximum
over all candidates, and a tie is listed, never broken by order.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field

from pipeline import normalise

# Words that say only that the car is electric: set aside when two model names are compared ('Kona Electric'
# is Parkers' 'kona-electric', 'Avenger Electric' its 'avenger'), and never a generation's label of their own
# ('grande-panda/electric-2025' is a generation, but 'Electric' in a name does not pick it).
POWER = {"electric", "electrified", "ev", "etech"}
LABEL_POWER = POWER | {"e"}


_YEARS = re.compile(r"\(\s*((?:19|20)\d\d)\s*-\s*((?:19|20)\d\d)?\s*\)")


def _model_words(s: str | None) -> list[str]:
    """A model name's words, letters and numbers apart ('ID.3' and 'id3' are id, 3; 'MG4' is mg, 4): 'E-Tech'
    one word, '+' read as 'plus' ('C-HR+'), leading zeros off ('Ora 03'), a printed span of years left out."""
    s = re.sub(r"e[\s-]*tech", "etech", _YEARS.sub(" ", normalise.fold(s)))
    out = []
    for w in normalise.words(s):
        plus = w.endswith("+")
        for t in re.findall(r"[a-z]+|\d+", w):
            out.append(t.lstrip("0") or "0" if t.isdigit() else t)
        if plus:
            out.append("plus")
    return out


def _printed_years(s: str | None) -> tuple[str, str] | None:
    m = _YEARS.search(normalise.fold(s))
    return (f"{m.group(1)}-01", f"{m.group(2) or m.group(1)}-12") if m else None


def _label(generation: str) -> str:
    return re.sub(r"-?\d{4}$", "", generation)


@dataclass
class Generation:
    make: str
    model: str
    generation: str
    exact: set[str] = field(default_factory=set)   # derivative names as printed
    alike: set[str] = field(default_factory=set)   # read alike
    since: list[str] = field(default_factory=list)
    until: list[str] = field(default_factory=list)
    open: bool = False
    derivatives: set[str] = field(default_factory=set)

    @property
    def label(self) -> str:
        return _label(self.generation)

    @property
    def start(self) -> int | None:
        m = re.search(r"(\d{4})$", self.generation)
        return int(m.group(1)) if m else None

    def label_words(self) -> list[str]:
        return [w for w in _model_words(self.label) if w not in LABEL_POWER]

    def row(self, shared: int) -> dict:
        return {"generation": self.generation, "label": self.label, "start": self.start,
                "since": min(self.since) if self.since else None,
                "until": None if self.open or not self.until else max(self.until),
                "derivatives": len(self.derivatives), "shared": shared}


def parkers_generations(conn: sqlite3.Connection) -> dict[tuple[str, str], dict[str, Generation]]:
    """(make slug, model slug) → generation → what Parkers says of it: its sitemap's derivative addresses
    and its derivative pages' names and on-sale dates."""
    out: dict[tuple[str, str], dict[str, Generation]] = {}
    for key, payload in conn.execute("SELECT spec_key, payload FROM specs WHERE source='parkers' ORDER BY spec_key"):
        p = json.loads(payload)
        mk, md, gen = p.get("make_slug"), p.get("model_slug"), p.get("generation")
        if not (mk and md and gen):
            continue
        g = out.setdefault((mk, md), {}).setdefault(gen, Generation(mk, md, gen))
        if key.startswith("parkers-sitemap:"):
            if p.get("entry") == "derivative":
                g.derivatives.add(p["slug"])
                g.alike.add(normalise.name_compact(p["slug"].replace("-", " "), mk))
        elif p.get("name"):
            g.derivatives.add(key.rsplit("/", 1)[-1])
            g.exact.add(p["name"])
            g.alike.add(normalise.name_compact(p["name"], mk))
            if p.get("on_sale_since"):
                g.since.append(p["on_sale_since"])
            if p.get("on_sale_until"):
                g.until.append(p["on_sale_until"])
            else:
                g.open = True
    return out


def _make_extras(parkers_make: str, make: str) -> list[list[str]]:
    """Each way Parkers' make reads as Carwow's, by the words of it left over: 'mercedes-amg' for 'mercedes'
    leaves ['amg'], and 'gwm-ora' for 'gwm' both [] (a make alias) and ['ora']; none when the makes differ."""
    want = normalise.make_key(make)
    ws = normalise.words(parkers_make)
    return [ws[k:] for k in range(len(ws), 0, -1) if normalise.make_key("-".join(ws[:k])) == want]


def _core(words: list[str], make_words: list[str]) -> list[str]:
    """A model name's words less those saying only 'electric', and less the make printed before it ('MG 5 EV')."""
    ws = [w for w in words if w not in POWER]
    if make_words and ws[:len(make_words)] == make_words and len(ws) > len(make_words):
        ws = ws[len(make_words):]
    return ws


def _closeness(a: list[str], b: list[str]) -> float:
    """How alike two model names read: 2 the same words ('e:Ny1' and 'eny1' alike), 1.9 the same less an 'e'
    ('500e' and '500-electric', 'Combo Life' and 'combo-e-life'), between 1 and 1.5 when one is the other with
    words after it ('Model 3 Performance' and 'model-3', the share of the longer the shorter is), else 0. After
    a one-word name, a number is another model ('Ioniq 3' is not 'ioniq-electric'); after a longer one it is a
    version ('AMG EQE 53' is 'mercedes-amg/eqe'). The same words in another order: 1.95 ('ForTwo EQ')."""
    if a == b or "".join(a) == "".join(b):
        return 2.0
    if sorted(a) == sorted(b):
        return 1.95
    a2, b2 = [w for w in a if w != "e"], [w for w in b if w != "e"]
    if a2 == b2:
        return 1.9
    short, long_ = sorted((a2, b2), key=len)
    if short and long_[:len(short)] == short and (len(short) > 1 or all(w.isalpha() for w in long_[len(short):])):
        return 1.0 + len("".join(short)) / len("".join(long_)) / 2
    return 0.0


@dataclass
class Candidate:
    path: str
    gens: dict[str, Generation]
    claimed: list[str]
    closeness: float
    exact: int
    alike: int
    on_sale: bool | None

    def key(self) -> tuple:
        return (self.exact, self.alike, self.closeness, self.on_sale is not False)

    def brief(self) -> dict:
        return {"parkers": self.path, "shared": self.exact, "shared_alike": self.alike, "reads_alike": round(self.closeness, 3),
                "generations": sorted(self.gens)}


def _years(names: list[dict]) -> tuple[str, str] | None:
    dates = sorted(d[:7] for n in names for d in (n.get("version_date"),) if d)
    return (dates[0], dates[-1]) if dates else None


def _on_sale(gens: dict[str, Generation], years: tuple[str, str] | None) -> bool | None:
    """Whether any generation was on sale over the months Carwow's price lists are dated (None: no dates)."""
    if not years:
        return None
    known = [g for g in gens.values() if g.since]
    if not known:
        return None
    return any(min(g.since) <= years[1] and (g.open or not g.until or max(g.until) >= years[0]) for g in known)


def build_map(conn: sqlite3.Connection) -> list[dict]:
    """One row per electric catalogue model: its Parkers model and generations, or why it has none."""
    parkers = parkers_generations(conn)
    registry: dict[tuple[str, str], list[dict]] = {}
    for mk, md, name, vd in conn.execute("SELECT make_slug, model_slug, name, version_date FROM derivatives ORDER BY cap_id"):
        registry.setdefault((mk, md), []).append({"name": name, "version_date": vd})
    models = conn.execute("SELECT slug, make, model, make_name, model_name FROM models WHERE electric=1 ORDER BY slug").fetchall()

    first: dict[str, dict] = {}
    for slug, make, model, make_name, model_name in models:
        name = model_name or model.replace("-", " ")
        words = _model_words(name)
        make_words = _model_words(make_name or make)
        regs = registry.get((make, model), [])
        exact = {r["name"] for r in regs}
        alike = {normalise.name_compact(n, make) for n in exact}
        years = _years(regs) or _printed_years(name)
        cands: list[Candidate] = []
        for (pmk, pmd), gens in sorted(parkers.items()):
            extras = _make_extras(pmk, make)
            if not extras:
                continue
            labels = {g: gens[g].label_words() for g in gens}
            claimed = sorted(g for g, lw in labels.items() if lw and all(w in words for w in lw))
            drop = {w for g in claimed for w in labels[g]}
            mine = _core([w for w in words if w not in drop], make_words)
            closeness = max(_closeness(mine, _core([w for w in extra + _model_words(pmd.replace("-", " ")) if w not in drop],
                                                   make_words)) for extra in extras)
            n_exact = sum(1 for n in exact if any(n in g.exact for g in gens.values()))
            n_alike = sum(1 for a in alike if any(a in g.alike for g in gens.values()))
            if closeness or n_alike:
                cands.append(Candidate(f"{pmk}/{pmd}", gens, claimed, closeness, n_exact, n_alike, _on_sale(gens, years)))
        first[slug] = {"slug": slug, "make": make, "model": model, "make_name": make_name, "model_name": model_name,
                       "registry": len(exact), "years": list(years) if years else None,
                       **_choose(cands, len(alike)), "_exact": exact, "_alike": alike}

    # Generations: once every model is placed, so each sees which others share its Parkers model.
    cand = {slug: r.pop("_cand", None) for slug, r in first.items()}
    names = {slug: (r.pop("_exact"), r.pop("_alike")) for slug, r in first.items()}
    on: dict[str, list[str]] = {}
    for slug, r in sorted(first.items()):
        if r["status"] == "placed":
            on.setdefault(cand[slug].path, []).append(slug)
    rows = []
    for slug, r in sorted(first.items()):
        c = cand[slug]
        if r["status"] == "placed" and c:
            others = [(s, cand[s], names[s]) for s in on[c.path] if s != slug]
            gens, why = _generations(c, others, *names[slug])
            r["parkers"] = c.path
            r["generations"] = [c.gens[g].row(_shared(c.gens[g], *names[slug])) for g in gens]
            if why:   # the Parkers model is known, its generation is not
                r["status"], r["why"] = "ambiguous", why
        rows.append(r)
    return rows


def _shared(g: Generation, exact: set[str], alike: set[str]) -> int:
    return len(exact & g.exact) or len(alike & g.alike)


def _choose(cands: list[Candidate], registry: int) -> dict:
    reads = [c for c in cands if c.closeness]
    others = [c.brief() for c in sorted(cands, key=lambda c: (c.key(), c.path), reverse=True)]
    if reads:
        best = max(c.key() for c in reads)
        top = sorted((c for c in reads if c.key() == best), key=lambda c: c.path)
        if len(top) > 1:
            return {"status": "ambiguous", "rule": None, "parkers": None, "generations": [], "candidates": [c.brief() for c in top],
                    "why": "the names of " + " and ".join(c.path for c in top) + " read alike and nothing tells them apart"}
        c = top[0]
        also = [o["parkers"] for o in others if o["parkers"] != c.path and o["reads_alike"]]
        return {"status": "placed", "rule": "name and derivatives" if c.exact or c.alike else "name", "_cand": c,
                "candidates": [o for o in others if o["parkers"] != c.path][:3],
                "why": ("also read alike: " + ", ".join(also)) if also else None}
    named = [c for c in cands if c.alike]
    if named:
        best = max(c.alike for c in named)
        top = sorted((c for c in named if c.alike == best), key=lambda c: c.path)
        if len(top) == 1 and best == registry:
            return {"status": "placed", "rule": "derivatives", "_cand": top[0], "candidates": others[1:3],
                    "why": f"no Parkers model's name reads alike; this one lists every derivative on Carwow's registry "
                           f"({registry})"}
        return {"status": "unplaced", "rule": None, "parkers": None, "generations": [], "candidates": others[:3],
                "why": f"no Parkers model's name reads alike; the most derivative names shared is {best} of {registry}, in "
                       + " and ".join(c.path for c in top)}
    return {"status": "unplaced", "rule": None, "parkers": None, "generations": [], "candidates": [],
            "why": "no electric Parkers model of this make reads alike" + (", and none shares a derivative name" if registry else "")}


def _generations(c: Candidate, others: list[tuple[str, Candidate, tuple[set[str], set[str]]]], exact: set[str],
                 alike: set[str]) -> tuple[list[str], str | None]:
    """The generations of `c` a Carwow model spans, given the other Carwow models placed on the same Parkers model."""
    if c.claimed:
        return c.claimed, None
    taken = {g for _, oc, _ in others for g in oc.claimed}
    free = [g for g in sorted(c.gens) if g not in taken]
    mine = {g for g in c.gens if _shared(c.gens[g], exact, alike)}
    if free:
        if mine & set(free):
            theirs = {g for _, _, (ex, al) in others for g in c.gens if _shared(c.gens[g], ex, al)}
            free = [g for g in free if g in mine or g not in theirs]
        return free, None
    if mine:
        return sorted(mine), None
    return sorted(c.gens), ("every generation of " + c.path + " is named by another Carwow model ("
                            + ", ".join(s for s, _, _ in others) + ") and none shares a derivative name with this one")


def write(conn: sqlite3.Connection) -> list[dict]:
    """The map into `model_map`, one row per catalogue model."""
    rows = build_map(conn)
    conn.execute("DELETE FROM model_map")
    conn.executemany("INSERT INTO model_map (slug, status, parkers_model, payload) VALUES (?,?,?,?)",
                     [(r["slug"], r["status"], r.get("parkers"), json.dumps(r, sort_keys=True, ensure_ascii=False)) for r in rows])
    return rows


def load(conn: sqlite3.Connection) -> list[dict]:
    try:
        return [json.loads(p) for (p,) in conn.execute("SELECT payload FROM model_map ORDER BY slug")]
    except sqlite3.OperationalError:   # a database built before the table existed
        return []
