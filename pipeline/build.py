"""The build: everything the app reads, derived from scratch on every run.

Inputs, and nothing else:
    the raw store         every page ever fetched (pipeline/raw.py), parsed again here
    the committed history the data/history files committed before the raw store existed, copied
                          into it and read with their matches taken out (pipeline/history.py)
    the default settings  data/seed/requirements.json (the quoting basis and the starting
                          saved searches), read from the repo

Steps, each over every record at once, so no answer depends on the order pages were read in:
    0. every record, from every source, into `records`: what it said and over which dates
    1. write what each source said (gold.py), page by page in date order; prices become
       sightings: one price one source showed for one offer at one instant
    2. derivatives: one per CAP id any record names (a specification row, the registry,
       a deals page's line), each in the form the matcher reads; nothing else makes one
    3. match: a record naming a CAP id is that derivative; a broker's or a used listing's
       text is matched by services/resolve.py against every derivative of its make and model
    4. fold each offer's sightings, in date order, into spans of an unchanged price
    5. the cars: one per derivative
    6. each Carwow catalogue model's Parkers model and generations (services/model_map.py)
    7. the resolver (services/resolver.py, BOARD.md T3): every record filtered against one master list of
       cars, Parkers' derivatives and the Carwow ones it lacks, with why, and the comparison of each
       record's car with today's lookups; until the switch, today's lookups still decide the cars

The database this writes is disposable: delete it and build again.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import re
import sqlite3
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from pipeline import code_keys, gold, history, normalise, stages
from pipeline.db import ROOT, connect, init_schema
from pipeline.providers import PROVIDERS
from pipeline.providers.parse import combustion
from pipeline.providers.types import Context, ParsedRecord, Target
from pipeline.raw import RawStore
from pipeline.services import autocars, model_map, resolve, resolver

SETTINGS_PROVIDER = "manual_seed"
# At the same instant a page we hold outranks the committed history's copy of what was read from it.
PRIORITY = {"history": 1}
# A sighting's own date is not part of what the record says.
UNDATED = ("observed_at", "captured_at", "confirmed_at")


@dataclass
class Sighting:
    at: str
    priority: int
    order: int
    provider: str
    key: str
    row: dict
    url: str | None = None


@dataclass
class Report:
    fetches: int = 0
    parsed: int = 0
    from_cache: int = 0
    parsed_by: dict[str, int] = field(default_factory=dict)   # source -> pages parsed (not from the cache)
    records: int = 0
    history_versions: int = 0
    history_rows: int = 0
    sightings: int = 0
    record_spans: int = 0
    failures: list[str] = field(default_factory=list)
    seconds: float = 0.0
    resolver: dict | None = None   # the resolver's summary (services/resolver.py)

    def lines(self) -> list[str]:
        out = [f"build: {self.fetches} fetches ({self.parsed} parsed, {self.from_cache} from the parse cache), "
               f"{self.records} records; {self.history_versions} committed history versions, {self.history_rows} rows; "
               f"{self.sightings} price sightings; {self.record_spans} record spans; {self.seconds:.1f} s"]
        if self.parsed_by:
            out.append("build: parsed, by source: " + ", ".join(f"{s} {n}" for s, n in sorted(self.parsed_by.items())))
        if self.failures:
            out.append(f"build: {len(self.failures)} fetches could not be parsed:")
            out += [f"  {f}" for f in self.failures[:20]]
            if len(self.failures) > 20:
                out.append(f"  ... and {len(self.failures) - 20} more")
        if self.resolver:
            out += resolver.report_lines(self.resolver)
        return out


# ---------------------------------------------------------------- parsing, with a cache

def code_versions(root: Path = ROOT) -> dict[str, str]:
    """Source -> the version of the code its parser can run (pipeline/code_keys.py), and of this
    file's parse path: a change to one reader re-parses its own source's pages, a change to a
    module several import re-parses each of theirs."""
    path = "".join(inspect.getsource(f) for f in PARSE_PATH).encode()
    return code_keys.source_keys(root, PROVIDERS, path)


class ParseCache:
    """Parsed records by (fetch id, its source's code version), so a build re-parses only new
    pages and pages whose parser changed. Disposable, like the build database."""

    def __init__(self, path: Path | str | None):
        if path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path)) if path else None
        self.current: set[str] | None = None
        if self.conn:
            self.conn.execute("CREATE TABLE IF NOT EXISTS parsed (fetch_id TEXT, code TEXT, records TEXT, PRIMARY KEY (fetch_id, code))")

    def get(self, fetch_id: str, code: str) -> list[ParsedRecord] | None:
        if not self.conn:
            return None
        row = self.conn.execute("SELECT records FROM parsed WHERE fetch_id=? AND code=?", (fetch_id, code)).fetchone()
        return [ParsedRecord(kind=k, key=key, row=r) for k, key, r in json.loads(row[0])] if row else None

    def put(self, fetch_id: str, code: str, records: list[ParsedRecord]) -> None:
        if self.conn:
            self.conn.execute("INSERT OR REPLACE INTO parsed VALUES (?,?,?)",
                              (fetch_id, code, json.dumps([[r.kind, r.key, r.row] for r in records], ensure_ascii=False)))

    def keep(self, codes: Iterable[str]) -> None:
        """Every source's current code version: closing drops the rows of every other."""
        self.current = set(codes)

    def close(self) -> None:
        if self.conn:
            if self.current:
                self.conn.execute(f"DELETE FROM parsed WHERE code NOT IN ({','.join('?' * len(self.current))})", sorted(self.current))
            self.conn.commit()
            self.conn.close()


def parse_entry(store: RawStore, e: dict, parts: list[dict] | None = None) -> tuple[str, list[ParsedRecord]]:
    """(when the page said it, its records): the parser reads the target as it was fetched,
    dated by the fetch (or by the archive's capture, for a Wayback copy). A parser that reads
    parts gets the responses the fetch was made of (`parts`: their index lines)."""
    cap = PROVIDERS[e["source"]].capabilities[e["capability"]]
    meta = dict(e.get("metadata") or {})
    meta.setdefault("observed_at", e["fetched_at"])
    if cap.reads_parts:
        meta["parts"] = [{"url": p.get("url"), "status": p.get("status"), "body": store.get(p["sha256"]) if p.get("sha256") else None}
                         for p in parts or []]
    return meta["observed_at"], list(cap.parse(store.get(e["sha256"]), Target(identifier=e["target"], metadata=meta)))


def part_index(entries: list[dict]) -> dict[tuple, list[dict]]:
    """(source, capability, target, fetched_at) → the parts kept with that fetch, in order, for the
    capabilities whose parser reads them."""
    out: dict[tuple, list[dict]] = {}
    for e in entries:
        if e.get("role") != "part":
            continue
        provider = PROVIDERS.get(e["source"])
        cap = provider.capabilities.get(e["capability"]) if provider else None
        if cap and cap.reads_parts:
            out.setdefault((e["source"], e["capability"], e["target"], e["fetched_at"]), []).append(e)
    for v in out.values():
        v.sort(key=lambda p: (p.get("metadata") or {}).get("part") or 0)
    return out


# What of this file the cached records depend on: the versions above hash its source.
PARSE_PATH = (parse_entry, part_index, ParseCache.get, ParseCache.put)


# ---------------------------------------------------------------- the build

def _by_kind(records: list[ParsedRecord]) -> dict[str, list[tuple[None, ParsedRecord]]]:
    out: dict[str, list[tuple[None, ParsedRecord]]] = {}
    for r in records:
        out.setdefault(r.kind, []).append((None, r))
    return out


def _offer_row(row: dict) -> dict:
    row = dict(row)
    row.pop("car_id", None)
    row.setdefault("present", 1)
    return row


class Build:
    def __init__(self, conn: sqlite3.Connection, store: RawStore | None, root: Path = ROOT, cache: ParseCache | None = None):
        self.conn, self.store, self.root, self.cache = conn, store, root, cache
        self.report = Report()
        self.sightings: list[Sighting] = []
        self.gen: dict[str, dict] = {}               # CAP id -> the derivative as the matcher reads it
        self.gen_from: dict[str, str] = {}           # CAP id -> what described it: spec | registry | deals
        self.combustion: set[str] = set()            # CAP ids a record names whose engine burns fuel: not cars of this app
        self.by_make: dict[str, list[dict]] = {}
        self.pins: dict[str, set[str]] = {}
        self.resolutions: dict[tuple[str, str], dict] = {}
        self.said: list[tuple] = []   # (source, kind, key, page, at, priority, origin, fetch, row): every record, for `records`
        self.order = 0
        self.levels: dict[str, dict] = {}   # per source, what each level holds (pipeline/stages.py)
        self.fetch_rows: list[tuple] = []

    # -- 1. what each source said

    def settings(self) -> None:
        """The default settings, from the repo: dated by the file's own date, so two builds of the same file agree."""
        ctx = Context(root=self.root)
        name = SETTINGS_PROVIDER
        for cap in PROVIDERS[name].capabilities.values():
            for t in cap.discover(Target(identifier="all"), ctx):
                records = list(cap.parse(cap.fetch(t, ctx).body, t))
                self.report.records += len(records)
                for r in records:
                    self._said(name, r.kind, r.key, t.identifier, "", 3, "settings", f"{name}:{t.identifier}", r.row)
                if records:
                    gold.write(self.conn, name, _by_kind(records), None, now=records[0].row.get("as_of") or "")

    def _said(self, source: str, kind: str, key: str, page: str, at: str, priority: int, origin: str, fetch: str | None,
              row: dict) -> None:
        self.said.append((source, kind, key, page or "", at or "", priority, origin, fetch, row))

    def _sight(self, at: str, priority: int, provider: str, row: dict, url: str | None) -> None:
        self.order += 1
        self.sightings.append(Sighting(at, priority, self.order, provider, row["offer_key"], _offer_row(row), url))

    def history(self, entries: list[dict]) -> None:
        rank = {c: i for i, c in enumerate(history.ORDER)}
        versions = sorted((e for e in entries if e.get("origin") in history.ORIGINS and e.get("sha256")),
                          key=lambda e: (e["fetched_at"], rank.get(e["capability"], 99)))
        for e in versions:
            try:
                rows = history.read(e["capability"], self.store.get(e["sha256"]))
            except Exception as ex:  # noqa: BLE001
                self.report.failures.append(f"history {e['target']} {e['fetched_at']}: {ex}")
                continue
            self.report.history_versions += 1
            self.report.history_rows += len(rows)
            self._apply_history(e["capability"], rows, e["id"])

    # A committed history file kept each key's latest state: the dates it read that way over.
    HISTORY_KINDS = {"models": ("model", "slug"), "specs": ("spec", "spec_key"), "derivatives": ("derivative", "cap_id"),
                     "options": ("options", "cap_id"), "configurations": ("configuration", "fsc"), "used": ("used", "listing_key")}
    HISTORY_SOURCE = {"derivatives": "carwow_model", "options": "carwow_options", "configurations": "hyundai_configurator"}

    def _apply_history(self, cap: str, rows: list[dict], fetch: str | None = None) -> None:
        c = self.conn
        for d in rows:
            p = d.get("payload")
            if cap in self.HISTORY_KINDS:
                kind, key = self.HISTORY_KINDS[cap]
                row = p if cap != "models" else {**(p or {}), **{k: d.get(k) for k in ("slug", "make", "model", "make_name", "model_name",
                                                                                         "electric", "has_deals", "has_specs")}}
                src = d.get("source") or self.HISTORY_SOURCE[cap]
                # A spec row says when its content last changed; the others only when they were last seen.
                for at in sorted({d.get("changed_at") or d["last_seen_at"], d["last_seen_at"]}):
                    self._said(src, kind, str(d[key]), "", at, PRIORITY["history"], "history", fetch, row)
            if cap == "models":
                cols = ("slug", "make", "model", "make_name", "model_name", "electric", "has_deals", "has_specs")
                gold.upsert_model(c, {**(p or {}), **{k: d.get(k) for k in cols}}, d["source"], None, None, d["last_seen_at"],
                                  d["first_seen_at"], d["last_seen_at"])
            elif cap == "specs":
                gold.upsert_spec(c, p, d["source"], None, None, d["last_seen_at"], d["first_seen_at"], d["last_seen_at"],
                                 d.get("changed_at"))
            elif cap == "derivatives":
                gold.upsert_derivative(c, p, "carwow_model", None, None, d["last_seen_at"], d["first_seen_at"], d["last_seen_at"])
            elif cap == "options":
                gold.upsert_options(c, p, None, None, d["last_seen_at"], d["first_seen_at"], d["last_seen_at"])
            elif cap == "configurations":
                gold.upsert_configuration(c, p, None, None, d["last_seen_at"], d["first_seen_at"], d["last_seen_at"])
            elif cap == "used":
                gold.upsert_used_listing(c, p, d["source"], None, None, d["last_seen_at"], d["first_seen_at"], d["last_seen_at"],
                                         present=int(d.get("present", 1)))
            elif cap == "used_observations":
                if c.execute("SELECT 1 FROM used_listings WHERE listing_key=?", (d["listing_key"],)).fetchone():
                    gold.upsert_used_span(c, d)
            elif cap == "backfill":
                c.execute("""INSERT INTO backfill_ledger (url, since, every_days, source, captures, done_at) VALUES (?,?,?,?,?,?)
                             ON CONFLICT(url, since, every_days) DO UPDATE SET done_at=MAX(backfill_ledger.done_at, excluded.done_at),
                               captures=excluded.captures, source=excluded.source""",
                          (d["url"], d["since"], int(d["every_days"]), d.get("source"), d.get("captures"), d["done_at"]))
            elif cap == "observations":
                row = dict(p, present=d.get("present", 1), status=d.get("status") or p.get("status"),
                           finance_type=d.get("finance_type") or p.get("finance_type"), offer_key=d["offer_key"])
                prio = PRIORITY["history"]
                for at in sorted({d["observed_at"], d.get("confirmed_at") or d["observed_at"]}):
                    self._sight(at, prio, d["source"], dict(row, observed_at=at), p.get("source_url"))
                    self._said(d["source"], "offer", d["offer_key"], "", at, prio, "history", fetch, dict(row, observed_at=at))

    def raws(self, entries: list[dict]) -> None:
        codes = code_versions() if self.cache else {}   # the code that runs, wherever the settings are read from
        if self.cache:
            self.cache.keep(codes.values())
        parts = part_index(entries)
        batches: list[tuple[str, int, dict, list[ParsedRecord]]] = []
        for i, e in enumerate(entries):
            if e.get("origin") in history.ORIGINS or e.get("role") == "part" or not e.get("sha256") or e.get("status") != 200:
                continue
            self.report.fetches += 1
            provider = PROVIDERS.get(e["source"])
            if not provider or e["capability"] not in provider.capabilities:
                self.report.failures.append(f"{e['source']}/{e['capability']} {e['target']}: no such parser")
                continue
            code = codes.get(e["source"], "")
            records = self.cache.get(e["id"], code) if self.cache else None
            meta = e.get("metadata") or {}
            at = meta.get("observed_at") or e["fetched_at"]
            if records is None:
                try:
                    at, records = parse_entry(self.store, e, parts.get((e["source"], e["capability"], e["target"], e["fetched_at"])))
                except Exception as ex:  # noqa: BLE001
                    self.report.failures.append(f"{e['source']}/{e['capability']} {e['target']} {e['fetched_at']}: {ex}")
                    continue
                self.report.parsed += 1
                self.report.parsed_by[e["source"]] = self.report.parsed_by.get(e["source"], 0) + 1
                if self.cache:
                    self.cache.put(e["id"], code, records)
            else:
                self.report.from_cache += 1
            batches.append((at, i, e, records))
        batches.sort(key=lambda b: (b[0], b[1]))
        for at, i, e, records in batches:
            self.report.records += len(records)
            gold.write(self.conn, e["source"], _by_kind([r for r in records if r.kind != "offer"]), None, now=at)
            for r in records:
                when = r.row.get("observed_at") or at if r.kind == "offer" else at
                self._said(e["source"], r.kind, r.key, e["target"], when, 2, e.get("origin", "live"), e["id"], r.row)
                if r.kind == "offer":
                    self._sight(when, 2, e["source"], r.row, e.get("url"))

    # -- 2. derivatives

    def derivatives(self) -> None:
        # For a derivative only a deals page describes: the line from the newest price list any page
        # printed, then the latest sighting, then the line itself, so reading order never decides.
        stubs: dict[str, tuple[tuple, dict]] = {}
        for s in self.sightings:
            ref = s.row.get("car_ref") or {}
            if ref.get("source") == "carwow-cap" and ref.get("stub") and ref.get("key"):
                rank = (ref["stub"].get("version_date") or "", s.at, json.dumps(ref["stub"], sort_keys=True))
                if ref["key"] not in stubs or rank > stubs[ref["key"]][0]:
                    stubs[ref["key"]] = (rank, ref["stub"])
        def burns(cap: str, trim: str | None, engine: str | None) -> bool:
            if combustion(f"{trim or ''} {engine or ''}"):
                self.combustion.add(cap)
                return True
            return False
        for cap, (_, stub) in stubs.items():
            if not burns(cap, stub.get("trim"), stub.get("engine")):
                self.gen[cap], self.gen_from[cap] = autocars.from_stub(stub), "deals"
        for r in self.conn.execute("SELECT cap_id, make_slug, model_slug, trim, engine, rrp, version_date, payload FROM derivatives"):
            p = json.loads(r["payload"])
            stub = {"cap_id": r["cap_id"], "make": p.get("make") or r["make_slug"], "make_slug": r["make_slug"],
                    "model": p.get("model") or r["model_slug"], "model_slug": r["model_slug"], "trim": r["trim"], "engine": r["engine"],
                    "rrp": r["rrp"], "version_date": r["version_date"]}
            if not burns(r["cap_id"], r["trim"], r["engine"]):
                self.gen[r["cap_id"]], self.gen_from[r["cap_id"]] = autocars.from_stub(stub), "registry"
        for r in self.conn.execute("SELECT spec_key, cap_id, payload FROM specs WHERE spec_key LIKE 'carwow-cap:%' AND cap_id IS NOT NULL"):
            p = json.loads(r["payload"])
            if p.get("make") and p.get("model") and not burns(r["cap_id"], p.get("trim"), p.get("engine")):
                self.gen[r["cap_id"]], self.gen_from[r["cap_id"]] = autocars.from_spec(p), "spec"
        # The registry's CAP name, so a record printing exactly that name is matched before any is read alike.
        names = {r["cap_id"]: json.loads(r["payload"]).get("name") for r in self.conn.execute("SELECT cap_id, payload FROM derivatives")}
        for cap, car in self.gen.items():
            if names.get(cap):
                car["cap_name"] = names[cap]
            self.by_make.setdefault(normalise.make_key(car.get("make")), []).append(car)

    # -- 3. matching

    def _candidates(self, ref: dict) -> list[dict]:
        make = ref.get("make") or ""
        # NCD's Kia listings print the make before the model ('KIA EV6 ELECTRIC ESTATE').
        model = re.sub(rf"^{re.escape(make)}\s+", "", ref.get("model") or "", flags=re.I) if make else ref.get("model")
        return [c for c in self.by_make.get(normalise.make_key(make), []) if gold.model_agrees(model, c)]

    def match(self, ref: dict, provider: str, text_match: bool = True) -> dict:
        """What one record names: {car_id, status, method, evidence, name_key}."""
        site, key = ref.get("source", provider), ref.get("key", "")
        if (site == "carwow-cap" and key in self.combustion) or combustion(ref.get("derivative") or ref.get("label")):
            return {"car_id": None, "status": "ignored", "method": "combustion"}
        if site == "carwow-cap":
            if key in self.gen:
                return {"car_id": autocars.auto_id(key), "status": "auto", "method": "stub" if self.gen_from[key] == "deals" else "cap-id"}
            return {"car_id": None, "status": "unmapped", "method": None}
        if text_match and ref.get("make"):
            res = resolve.choose(ref, self._candidates(ref), self.pins)
            out = {"method": res.method, "evidence": res.evidence, "name_key": resolve.name_key(ref.get("derivative") or ref.get("label"))}
            if res.car_id:
                return {**out, "car_id": res.car_id, "status": "auto"}
            return {**out, "car_id": None, "status": "conflict" if res.method == "conflict" else "unmapped"}
        return {"car_id": None, "status": "unmapped", "method": None}

    def _pin_pass(self, refs: list[dict]) -> None:
        """The 'name' rule's pins: CAP names that some record's own RRP, or its registry name exactly as printed,
        tied to one twin."""
        self.pins = {}
        for ref in refs:
            if ref.get("make") and ref.get("source") != "carwow-cap":
                res = resolve.choose(ref, self._candidates(ref), None)
                exact = res.evidence.get("score") == "exact name" and len(res.evidence.get("twins") or []) == 1
                if res.car_id and (res.method == "rrp" or exact):
                    for k in resolve.pin_keys(ref.get("derivative") or ref.get("label")):
                        self.pins.setdefault(k, set()).add(res.car_id)

    def _note(self, ref: dict, provider: str, m: dict, at: str, url: str | None) -> None:
        """How one source's name resolved, for the Data page: from its latest sighting (ties by content)."""
        k = (ref.get("source", provider), ref.get("key", ""))
        row = {**m, "label": ref.get("label") or ref.get("derivative"), "example_url": url}
        rank = (at, json.dumps(row, sort_keys=True, default=str))
        cur = self.resolutions.get(k)
        if cur is None:
            self.resolutions[k] = {**row, "first_seen_at": at, "last_seen_at": at, "_rank": rank}
            return
        first, last = min(cur["first_seen_at"], at), max(cur["last_seen_at"], at)
        if rank > cur["_rank"]:
            cur.clear()
            cur.update(row, _rank=rank)
        cur["first_seen_at"], cur["last_seen_at"] = first, last

    def resolve(self) -> dict[str, str]:
        """The car of every offer, spec row and used listing. Returns offer key -> car."""
        latest: dict[str, Sighting] = {}
        for s in self.sightings:
            if s.key not in latest or (s.at, s.priority, s.order) > (latest[s.key].at, latest[s.key].priority, latest[s.key].order):
                latest[s.key] = s
        used_rows = self.conn.execute("SELECT listing_key, source, payload FROM used_listings").fetchall()
        used = [(r["listing_key"], json.loads(r["payload"]).get("car_ref") or {}) for r in used_rows]
        used_source = {r["listing_key"]: r["source"] for r in used_rows}
        # Pins from every sighting, not just the latest: a page that printed the RRP once has tied that CAP name to one twin.
        refs = {json.dumps(r, sort_keys=True): r for r in [s.row.get("car_ref") or {} for s in self.sightings] + [ref for _, ref in used]
                if r.get("rrp")}
        self._pin_pass(list(refs.values()))

        car_of: dict[str, str] = {}
        for key, s in latest.items():
            tally = self._matched(s.provider, "offers")
            ref = s.row.get("car_ref") or {}
            m = self.match(ref, s.provider)
            self._note(ref, s.provider, m, s.at, s.url)
            if m["car_id"]:
                car_of[key] = m["car_id"]
                tally["matched"] += 1
            elif m.get("status") == "conflict":
                tally["conflict"] += 1
        first = {}
        for s in self.sightings:
            first[s.key] = min(first.get(s.key, s.at), s.at)
        for key, s in latest.items():
            ref = s.row.get("car_ref") or {}
            k = (ref.get("source", s.provider), ref.get("key", ""))
            if k in self.resolutions:
                self.resolutions[k]["first_seen_at"] = min(self.resolutions[k]["first_seen_at"], first[key])

        for r in self.conn.execute("SELECT spec_key, source, payload, first_seen_at, last_seen_at FROM specs").fetchall():
            ref = json.loads(r["payload"]).get("car_ref") or {}
            tally = self._matched(r["source"], "specs")
            if not ref:
                continue
            m = self.match(ref, r["source"], text_match=False)
            if m["car_id"]:
                tally["matched"] += 1
                self.conn.execute("UPDATE specs SET car_id=? WHERE spec_key=?", (m["car_id"], r["spec_key"]))
                if ref.get("source") == "carwow-cap":
                    self._note(ref, r["source"], m, r["first_seen_at"], None)
                    self.resolutions[(ref["source"], ref["key"])]["last_seen_at"] = max(
                        self.resolutions[(ref["source"], ref["key"])]["last_seen_at"], r["last_seen_at"])

        for listing_key, ref in used:
            tally = self._matched(used_source[listing_key], "used")
            car = resolve.choose(ref, self._candidates(ref), self.pins).car_id if ref.get("make") else None
            if car:
                tally["matched"] += 1
                self.conn.execute("UPDATE used_listings SET car_id=? WHERE listing_key=?", (car, listing_key))
        return car_of

    def _matched(self, provider: str, kind: str) -> dict:
        """The running count, for one source and kind of record, of how many there are and how many name a car."""
        t = self.levels.setdefault(provider, {}).setdefault("matched", {}).setdefault(kind, {"total": 0, "matched": 0, "conflict": 0})
        t["total"] += 1
        return t

    # -- 4. prices as spans

    def fold(self, car_of: dict[str, str]) -> int:
        by_key: dict[str, dict[str, Sighting]] = {}
        for s in self.sightings:
            at_key = by_key.setdefault(s.key, {})
            cur = at_key.get(s.at)
            if cur is None or (s.priority, s.order) > (cur.priority, cur.order):
                at_key[s.at] = s
        n = 0
        for key, points in by_key.items():
            car = car_of.get(key)
            if not car:
                continue
            spans: list[list] = []   # [first sighting, last seen at, fingerprint, present]
            for at in sorted(points):
                s = points[at]
                fp, present = gold.fingerprint(s.row), int(s.row.get("present", 1))
                if spans and spans[-1][3] and present and spans[-1][2] == fp:
                    spans[-1][1] = at
                    continue
                spans.append([s, None, fp, present])
            for s, last, fp, present in spans:
                r = s.row
                self.conn.execute(
                    """INSERT INTO offer_observations (offer_key, car_id, source, observed_at, confirmed_at, present, finance_type, status,
                         verification, seller, vehicle_price, monthly_payment, apr, gfv, fingerprint, payload)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (key, car, s.provider, s.at, last, present, r["finance_type"], r["status"], r.get("verification"),
                     r.get("dealer") or r.get("source"), r.get("vehicle_price"), r.get("monthly_payment"), r.get("apr"), r.get("gfv"),
                     fp, gold._dump(dict(r, car_id=car, observed_at=s.at))),
                )
                n += 1
        return n

    def write_records(self) -> int:
        """`records`: every record folded, per source, kind and key, in date order, into spans of
        unchanged content. Ties at one instant fall by priority, then by content, never by reading order."""
        groups: dict[tuple[str, str, str, str], list[tuple]] = {}
        for src, kind, key, page, at, prio, origin, fetch, row in self.said:
            content = {k: v for k, v in row.items() if k not in UNDATED}
            dumped = gold._dump(content)
            fp = hashlib.sha1(dumped.encode()).hexdigest()[:16]
            groups.setdefault((src, kind, key, page), []).append((at, prio, fp, origin, fetch or "", dumped))
        out = []
        for (src, kind, key, page), points in sorted(groups.items()):
            span = None
            for at, prio, fp, origin, fetch, dumped in sorted(points):
                if span and span["fp"] == fp:
                    span.update(last=at, last_fetch=fetch, n=span["n"] + 1)
                    continue
                if span:
                    out.append(span)
                span = {"key": (src, kind, key, page), "first": at, "last": at, "n": 1, "origin": origin, "first_fetch": fetch,
                        "last_fetch": fetch, "fp": fp, "row": dumped}
            out.append(span)
        self.conn.executemany(
            "INSERT INTO records (source, kind, record_key, page, first_seen_at, last_seen_at, sightings, origin, first_fetch, last_fetch, "
            "fingerprint, row) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [(*s["key"], s["first"], s["last"], s["n"], s["origin"], s["first_fetch"] or None, s["last_fetch"] or None, s["fp"], s["row"])
             for s in out])
        self.report.record_spans = len(out)
        return len(out)

    # -- 5. the cars, and how every source's naming resolved

    def cars(self) -> None:
        def put(car: dict, source: str) -> None:
            self.conn.execute(
                """INSERT OR REPLACE INTO cars (id, make, model, trim, model_year, seats, battery_kwh, wltp_range_mi, width_mm,
                     list_price_gbp, grant_gbp, heat_pump, internal_v2l, payload, source, artifact_id, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,?)""",
                (car["id"], car["make"], car["model"], car.get("trim"), car.get("model_year"), car.get("seats"), car.get("battery_kwh"),
                 car.get("wltp_range_mi"), car.get("width_mm"), car.get("list_price_gbp"), car.get("grant_gbp"), car.get("heat_pump"),
                 car.get("internal_v2l"), gold._dump(car), source, ""))
        src = {"spec": "carwow_specs", "registry": "carwow_model", "deals": "carwow_deals"}
        for cap, car in sorted(self.gen.items()):
            put(car, src[self.gen_from[cap]])

    def trim_map(self) -> None:
        """How every source's name resolved (`trim_map`, which `pipeline trims` and the Data page read)."""
        for (site, key), m in sorted(self.resolutions.items()):
            ev = m.get("evidence")
            self.conn.execute(
                "INSERT INTO trim_map (source, source_key, car_id, status, label, example_url, first_seen_at, last_seen_at, method, "
                "evidence, name_key) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (site, key, m["car_id"], m["status"], m.get("label"), m.get("example_url"), m["first_seen_at"], m["last_seen_at"],
                 m.get("method"), resolve.dump_evidence(ev) if ev else None, m.get("name_key")))

    def logs(self) -> None:
        """The scraper's run log and the build log (the Data page shows them), the Wayback backfill's finished
        pages, and what each level holds per source."""
        self.stage_tables()
        if not self.store:
            return
        for r in self.store.read_log("runs"):
            self.conn.execute(
                "INSERT INTO runs (source, capability, target, started_at, finished_at, status, artifacts, records, unmapped, errors, error, "
                "skipped, deferred, new_bodies, allowance) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (r["source"], r["capability"], r.get("target", "all"), r["started_at"], r.get("finished_at"), r["status"],
                 r.get("fetches", 0), r.get("records", 0), 0, r.get("errors", 0), r.get("error"), r.get("skipped", 0),
                 r.get("deferred", 0), r.get("new_bodies", 0), json.dumps(r["allowance"]) if r.get("allowance") else None))
        for b in self.store.read_log("builds"):
            self.conn.execute("INSERT INTO builds (finished_at, payload) VALUES (?,?)", (b.get("finished_at"), json.dumps(b, sort_keys=True)))
        for d in self.store.read_log("backfill"):
            self.conn.execute("""INSERT INTO backfill_ledger (url, since, every_days, source, captures, done_at) VALUES (?,?,?,?,?,?)
                                 ON CONFLICT(url, since, every_days) DO UPDATE SET done_at=MAX(backfill_ledger.done_at, excluded.done_at),
                                   captures=excluded.captures, source=excluded.source""",
                              (d["url"], d["since"], int(d["every_days"]), d.get("source"), d.get("captures"), d["done_at"]))

    def stage_tables(self) -> None:
        """Per source: the raw store (counted while reading), records (from `records`), matched (counted while
        matching); each night's responses; and the snapshot's publishes, from git."""
        for r in self.conn.execute("SELECT source, kind, COUNT(DISTINCT record_key) AS n, "
                                   "COUNT(DISTINCT CASE WHEN origin='live' THEN record_key END) AS live FROM records GROUP BY source, kind"):
            self.levels.setdefault(r["source"], {}).setdefault("records", {})[r["kind"]] = {"keys": r["n"], "first_seen_live": r["live"]}
        for provider, lv in sorted(self.levels.items()):
            self.conn.execute("INSERT INTO source_levels (provider, payload) VALUES (?,?)", (provider, json.dumps(lv, sort_keys=True)))
        self.conn.executemany("INSERT INTO fetch_nights (night, source, responses, failed, refused) VALUES (?,?,?,?,?)", self.fetch_rows)
        self.conn.executemany("INSERT OR IGNORE INTO publishes (sha, at, subject) VALUES (?,?,?)",
                              [(p["sha"], p["at"], p["subject"]) for p in stages.publishes(self.root)])

    def run(self) -> Report:
        started = time.monotonic()
        entries = list(self.store.entries()) if self.store else []
        self.levels = {src: {"raw": lv} for src, lv in stages.raw_levels(entries).items()}
        self.fetch_rows = stages.fetch_nights(entries)
        self.settings()
        if self.store:
            self.history(entries)
            self.raws(entries)
        self.finish()
        self.logs()
        self.conn.commit()
        self.report.seconds = time.monotonic() - started
        return self.report

    def finish(self) -> None:
        """Everything after reading: derivatives, cars, matching, spans."""
        gold.retire_sampled(self.conn)
        gold.backfill_used_spans(self.conn)
        self.derivatives()
        self.cars()
        model_map.write(self.conn)   # each Carwow model's Parkers model, for the resolver (T2); it matches nothing yet
        car_of = self.resolve()
        self.trim_map()
        self.report.sightings = len(self.sightings)
        self.fold(car_of)
        self.write_records()
        self.report.resolver = resolver.run(self.conn)   # reads what the steps above wrote; changes none of it


def build(db_path: Path | str, store: RawStore | None, root: Path = ROOT, cache_path: Path | str | None = None) -> Report:
    """Build the database at `db_path` from scratch (written beside it, then moved into place)."""
    db_path = Path(db_path)
    tmp = db_path.with_name(db_path.name + ".building")
    for p in (tmp, Path(f"{tmp}-wal"), Path(f"{tmp}-shm")):
        if p.exists():
            p.unlink()
    conn = connect(tmp)
    init_schema(conn)
    cache = ParseCache(cache_path)
    try:
        report = Build(conn, store, root, cache).run()
    finally:
        cache.close()
        conn.execute("PRAGMA journal_mode = DELETE")
        conn.close()
    for p in (db_path, Path(f"{db_path}-wal"), Path(f"{db_path}-shm")):
        if p.exists():
            p.unlink()
    tmp.replace(db_path)
    return report


def build_memory(store: RawStore | None, root: Path = ROOT) -> tuple[sqlite3.Connection, Report]:
    """A build into an in-memory database (tests)."""
    conn = connect(":memory:")
    init_schema(conn)
    return conn, Build(conn, store, root).run()
