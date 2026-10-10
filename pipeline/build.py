"""The build: everything the app reads, derived from scratch on every run.

Inputs, and nothing else:
    the raw store         every page ever fetched (pipeline/raw.py), parsed again here
    the legacy history    the committed data/history files copied into the raw store, read
                          with their matches taken out (pipeline/legacy.py)
    the owner's own files data/seed (cars, offers, requirements, picks, the trim map's
                          decisions) and data/pastes, read from the repo

Steps, each over every record at once, so no answer depends on the order pages were read in:
    1. write what each source said (gold.py), page by page in date order; prices become
       sightings: one price one source showed for one offer at one instant
    2. derivatives: one per CAP id any record names (a specification row, the registry,
       a deals page's line), each in the form the matcher reads; nothing else makes one
    3. match: a record naming a CAP id is that derivative; a broker's or a used listing's
       text is matched by services/resolve.py against every derivative of its make and
       model; the owner's decisions (data/seed/trim_map.json) override both
    4. fold each offer's sightings, in date order, into spans of an unchanged price
    5. the cars: every derivative, and every car the owner entered. A derivative the owner
       entered appears once, as the owner's entry, carrying its CAP id.

The database this writes is disposable: delete it and build again.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

from pipeline import gold, legacy
from pipeline.db import ROOT, connect, init_schema
from pipeline.providers import PROVIDERS
from pipeline.providers.types import Context, ParsedRecord, Target
from pipeline.raw import RawStore
from pipeline.services import autocars, resolve

OWNER_PROVIDERS = ("manual_seed", "carwow_paste")
# At the same instant a page we hold outranks a legacy copy of what was read from it.
PRIORITY = {"legacy": 1}


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
    records: int = 0
    legacy_versions: int = 0
    legacy_rows: int = 0
    sightings: int = 0
    failures: list[str] = field(default_factory=list)
    seconds: float = 0.0

    def lines(self) -> list[str]:
        out = [f"build: {self.fetches} fetches ({self.parsed} parsed, {self.from_cache} from the parse cache), "
               f"{self.records} records; {self.legacy_versions} legacy history versions, {self.legacy_rows} rows; "
               f"{self.sightings} price sightings; {self.seconds:.1f} s"]
        if self.failures:
            out.append(f"build: {len(self.failures)} fetches could not be parsed:")
            out += [f"  {f}" for f in self.failures[:20]]
            if len(self.failures) > 20:
                out.append(f"  ... and {len(self.failures) - 20} more")
        return out


# ---------------------------------------------------------------- parsing, with a cache

def code_version(root: Path = ROOT) -> str:
    """Every file a parser can run: a change to any of them re-parses everything."""
    h = hashlib.sha256()
    files = sorted((root / "pipeline" / "providers").glob("*.py")) + [root / "pipeline" / "services" / f
                                                                      for f in ("features.py", "facts.py")]
    for p in files:
        h.update(p.name.encode())
        h.update(p.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()[:16]


class ParseCache:
    """Parsed records by (fetch id, code version), so a build re-parses only new pages and
    pages whose parser changed. Disposable, like the build database."""

    def __init__(self, path: Path | str | None):
        self.conn = sqlite3.connect(str(path)) if path else None
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

    def close(self) -> None:
        if self.conn:
            self.conn.execute("DELETE FROM parsed WHERE code <> (SELECT code FROM parsed ORDER BY rowid DESC LIMIT 1)")
            self.conn.commit()
            self.conn.close()


def parse_entry(store: RawStore, e: dict) -> tuple[str, list[ParsedRecord]]:
    """(when the page said it, its records): the parser reads the target as it was fetched,
    dated by the fetch (or by the archive's capture, for a Wayback copy)."""
    cap = PROVIDERS[e["source"]].capabilities[e["capability"]]
    meta = dict(e.get("metadata") or {})
    meta.setdefault("observed_at", e["fetched_at"])
    return meta["observed_at"], list(cap.parse(store.get(e["sha256"]), Target(identifier=e["target"], metadata=meta)))


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
        self.owner_cars: list[dict] = []
        self.owner_offer_cars: dict[str, str] = {}   # offer key -> the car the owner entered it against
        self.decisions: dict[tuple[str, str], dict] = {}
        self.gen: dict[str, dict] = {}               # CAP id -> the derivative as the matcher reads it
        self.gen_from: dict[str, str] = {}           # CAP id -> what described it: spec | registry | deals
        self.alias: dict[str, str] = {}              # CAP id -> the owner's car for that derivative
        self.by_make: dict[str, list[dict]] = {}
        self.pins: dict[str, set[str]] = {}
        self.resolutions: dict[tuple[str, str], dict] = {}
        self.order = 0

    # -- 1. what each source said

    def owner(self) -> None:
        ctx = Context(root=self.root)
        for name in OWNER_PROVIDERS:
            provider = PROVIDERS[name]
            for cap in provider.capabilities.values():
                for t in cap.discover(Target(identifier="all"), ctx):
                    fetched = cap.fetch(t, ctx)
                    records = list(cap.parse(fetched.body, t))
                    self.report.records += len(records)
                    for r in records:
                        if r.kind == "car":
                            self.owner_cars.append(r.row)
                        elif r.kind == "trim_map":
                            self.decisions[(r.row["source"], r.row["source_key"])] = r.row
                        elif r.kind == "offer":
                            if r.row.get("car_id"):
                                self.owner_offer_cars[r.row["offer_key"]] = r.row["car_id"]
                            self._sight(r.row["observed_at"], 3, name, r.row, fetched.url)
                    reqs = [r for r in records if r.kind == "requirements"]
                    if reqs:   # dated by the file's own date, so two builds of the same files agree
                        gold.write(self.conn, name, _by_kind(reqs), None, now=reqs[0].row.get("as_of") or "")

    def _sight(self, at: str, priority: int, provider: str, row: dict, url: str | None) -> None:
        self.order += 1
        self.sightings.append(Sighting(at, priority, self.order, provider, row["offer_key"], _offer_row(row), url))

    def legacy(self, entries: list[dict]) -> None:
        rank = {c: i for i, c in enumerate(legacy.ORDER)}
        versions = sorted((e for e in entries if e.get("origin") == legacy.SOURCE and e.get("sha256")),
                          key=lambda e: (e["fetched_at"], rank.get(e["capability"], 99)))
        for e in versions:
            rows = legacy.read(e["capability"], self.store.get(e["sha256"]))
            self.report.legacy_versions += 1
            self.report.legacy_rows += len(rows)
            self._apply_legacy(e["capability"], rows)

    def _apply_legacy(self, cap: str, rows: list[dict]) -> None:
        c = self.conn
        for d in rows:
            p = d.get("payload")
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
                prio = PRIORITY["legacy"]
                self._sight(d["observed_at"], prio, d["source"], dict(row, observed_at=d["observed_at"]), p.get("source_url"))
                if d.get("confirmed_at") and d["confirmed_at"] != d["observed_at"]:
                    self._sight(d["confirmed_at"], prio, d["source"], dict(row, observed_at=d["confirmed_at"]), p.get("source_url"))

    def raws(self, entries: list[dict]) -> None:
        code = code_version(self.root)
        batches: list[tuple[str, int, dict, list[ParsedRecord]]] = []
        for i, e in enumerate(entries):
            if e.get("origin") == legacy.SOURCE or e.get("role") == "part" or not e.get("sha256") or e.get("status") != 200:
                continue
            self.report.fetches += 1
            provider = PROVIDERS.get(e["source"])
            if not provider or e["capability"] not in provider.capabilities:
                self.report.failures.append(f"{e['source']}/{e['capability']} {e['target']}: no such parser")
                continue
            records = self.cache.get(e["id"], code) if self.cache else None
            meta = e.get("metadata") or {}
            at = meta.get("observed_at") or e["fetched_at"]
            if records is None:
                try:
                    at, records = parse_entry(self.store, e)
                except Exception as ex:  # noqa: BLE001
                    self.report.failures.append(f"{e['source']}/{e['capability']} {e['target']} {e['fetched_at']}: {ex}")
                    continue
                self.report.parsed += 1
                if self.cache:
                    self.cache.put(e["id"], code, records)
            else:
                self.report.from_cache += 1
            batches.append((at, i, e, records))
        batches.sort(key=lambda b: (b[0], b[1]))
        for at, i, e, records in batches:
            self.report.records += len(records)
            gold.write(self.conn, e["source"], _by_kind([r for r in records if r.kind not in ("offer", "car", "trim_map")]), None, now=at)
            for r in records:
                if r.kind == "offer":
                    self._sight(r.row.get("observed_at") or at, 2, e["source"], r.row, e.get("url"))

    # -- 2. derivatives

    def derivatives(self) -> None:
        stubs: dict[str, tuple[str, dict]] = {}
        for s in self.sightings:
            ref = s.row.get("car_ref") or {}
            if ref.get("source") == "carwow-cap" and ref.get("stub") and ref.get("key"):
                if ref["key"] not in stubs or s.at >= stubs[ref["key"]][0]:
                    stubs[ref["key"]] = (s.at, ref["stub"])
        for cap, (_, stub) in stubs.items():
            self.gen[cap], self.gen_from[cap] = autocars.from_stub(stub), "deals"
        for r in self.conn.execute("SELECT cap_id, make_slug, model_slug, trim, engine, rrp, version_date, payload FROM derivatives"):
            p = json.loads(r["payload"])
            stub = {"cap_id": r["cap_id"], "make": p.get("make") or r["make_slug"], "make_slug": r["make_slug"],
                    "model": p.get("model") or r["model_slug"], "model_slug": r["model_slug"], "trim": r["trim"], "engine": r["engine"],
                    "rrp": r["rrp"], "version_date": r["version_date"]}
            self.gen[r["cap_id"]], self.gen_from[r["cap_id"]] = autocars.from_stub(stub), "registry"
        for r in self.conn.execute("SELECT spec_key, cap_id, payload FROM specs WHERE spec_key LIKE 'carwow-cap:%' AND cap_id IS NOT NULL"):
            p = json.loads(r["payload"])
            if p.get("make") and p.get("model"):
                self.gen[r["cap_id"]], self.gen_from[r["cap_id"]] = autocars.from_spec(p), "spec"
        owner_ids = {c["id"] for c in self.owner_cars}
        for (site, key), d in self.decisions.items():
            if site == "carwow-cap" and d.get("car_id") in owner_ids:
                self.alias[key] = d["car_id"]
        for car in self.gen.values():
            self.by_make.setdefault((car.get("make") or "").lower(), []).append(car)

    def car_for(self, cap: str) -> str:
        return self.alias.get(cap) or autocars.auto_id(cap)

    def _named(self, car_id: str | None) -> str | None:
        """A matcher's answer (a generated id) as the car it is: the owner's entry when there is one."""
        if car_id and car_id.startswith("carwow-cap:"):
            return self.car_for(car_id.split(":", 1)[1])
        return car_id

    # -- 3. matching

    def _candidates(self, ref: dict) -> list[dict]:
        return [c for c in self.by_make.get((ref.get("make") or "").lower(), []) if gold.model_agrees(ref.get("model"), c)]

    def match(self, ref: dict, provider: str, text_match: bool = True) -> dict:
        """What one record names: {car_id, status, method, evidence, name_key}."""
        site, key = ref.get("source", provider), ref.get("key", "")
        d = self.decisions.get((site, key))
        if d and d.get("car_id"):
            return {"car_id": d["car_id"], "status": "mapped", "method": "manual"}
        if site == "carwow-cap":
            if key in self.gen:
                return {"car_id": self.car_for(key), "status": "auto", "method": "stub" if self.gen_from[key] == "deals" else "cap-id"}
            return {"car_id": None, "status": d["status"] if d else "unmapped", "method": None}
        if text_match and ref.get("make"):
            res = resolve.choose(ref, self._candidates(ref), self.pins)
            out = {"method": res.method, "evidence": res.evidence, "name_key": resolve.name_key(ref.get("derivative") or ref.get("label"))}
            if res.car_id:
                return {**out, "car_id": self._named(res.car_id), "generated_id": res.car_id, "status": "auto"}
            if res.method == "conflict":
                return {**out, "car_id": None, "status": "conflict"}
            return {**out, "car_id": None, "status": d.get("status", "ignored") if d else "unmapped"}
        return {"car_id": None, "status": d.get("status", "ignored") if d else "unmapped", "method": None}

    def _pin_pass(self, refs: list[dict]) -> None:
        """The 'name' rule's pins: CAP names that some record's own RRP tied to one twin."""
        self.pins = {}
        for ref in refs:
            if ref.get("make") and ref.get("source") != "carwow-cap":
                res = resolve.choose(ref, self._candidates(ref), None)
                if res.method == "rrp" and res.car_id:
                    self.pins.setdefault(resolve.name_key(ref.get("derivative") or ref.get("label")), set()).add(res.car_id)

    def _note(self, ref: dict, provider: str, m: dict, at: str, url: str | None) -> None:
        k = (ref.get("source", provider), ref.get("key", ""))
        cur = self.resolutions.get(k)
        if cur is None:
            self.resolutions[k] = {**m, "label": ref.get("label") or ref.get("derivative"), "example_url": url,
                                   "first_seen_at": at, "last_seen_at": at}
        else:
            cur["first_seen_at"] = min(cur["first_seen_at"], at)
            cur["last_seen_at"] = max(cur["last_seen_at"], at)

    def resolve(self) -> dict[str, str]:
        """The car of every offer, spec row and used listing. Returns offer key -> car."""
        latest: dict[str, Sighting] = {}
        for s in self.sightings:
            if s.key not in latest or (s.at, s.priority, s.order) > (latest[s.key].at, latest[s.key].priority, latest[s.key].order):
                latest[s.key] = s
        used = [(r["listing_key"], json.loads(r["payload"]).get("car_ref") or {})
                for r in self.conn.execute("SELECT listing_key, payload FROM used_listings")]
        # Pins from every sighting, not just the latest: a page that printed the RRP once has tied that CAP name to one twin.
        refs = {json.dumps(r, sort_keys=True): r for r in [s.row.get("car_ref") or {} for s in self.sightings] + [ref for _, ref in used]
                if r.get("rrp")}
        self._pin_pass(list(refs.values()))

        car_of: dict[str, str] = {}
        for key, s in latest.items():
            if key in self.owner_offer_cars:
                car_of[key] = self.owner_offer_cars[key]
                continue
            ref = s.row.get("car_ref") or {}
            m = self.match(ref, s.provider)
            self._note(ref, s.provider, m, s.at, s.url)
            if m["car_id"]:
                car_of[key] = m["car_id"]
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
            if not ref:
                continue
            m = self.match(ref, r["source"], text_match=False)
            if m["car_id"]:
                self.conn.execute("UPDATE specs SET car_id=? WHERE spec_key=?", (m["car_id"], r["spec_key"]))
                if ref.get("source") == "carwow-cap":
                    self._note(ref, r["source"], m, r["first_seen_at"], None)
                    self.resolutions[(ref["source"], ref["key"])]["last_seen_at"] = max(
                        self.resolutions[(ref["source"], ref["key"])]["last_seen_at"], r["last_seen_at"])

        for listing_key, ref in used:
            if ref.get("make"):
                res = resolve.choose(ref, self._candidates(ref), self.pins)
                if res.car_id:
                    self.conn.execute("UPDATE used_listings SET car_id=? WHERE listing_key=?", (self._named(res.car_id), listing_key))
        return car_of

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
        cap_of = {v: k for k, v in self.alias.items()}
        for c in self.owner_cars:
            put(dict(c, cap_id=c.get("cap_id") or cap_of.get(c["id"])) if cap_of.get(c["id"]) or c.get("cap_id") else c, "manual_seed")
        src = {"spec": "carwow_specs", "registry": "carwow_model", "deals": "carwow_deals"}
        for cap, car in sorted(self.gen.items()):
            if cap not in self.alias:
                put(car, src[self.gen_from[cap]])

    def trim_map(self) -> None:
        for (site, key), d in self.decisions.items():
            if (site, key) not in self.resolutions:
                self.conn.execute(
                    "INSERT INTO trim_map (source, source_key, car_id, status, label, example_url, note, first_seen_at, last_seen_at, method) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (site, key, d.get("car_id"), d.get("status") or ("mapped" if d.get("car_id") else "ignored"), d.get("label"),
                     d.get("example_url"), d.get("note"), "", "", "manual" if d.get("car_id") else None))
        for (site, key), m in sorted(self.resolutions.items()):
            d = self.decisions.get((site, key)) or {}
            ev = m.get("evidence")
            self.conn.execute(
                "INSERT INTO trim_map (source, source_key, car_id, status, label, example_url, note, first_seen_at, last_seen_at, method, "
                "evidence, name_key) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (site, key, m["car_id"], m["status"], m.get("label") or d.get("label"), m.get("example_url"), d.get("note"),
                 m["first_seen_at"], m["last_seen_at"], m.get("method"), resolve.dump_evidence(ev) if ev else None, m.get("name_key")))

    def logs(self) -> None:
        """The scraper's run log (the Data page shows it) and the Wayback backfill's finished pages."""
        if not self.store:
            return
        for r in self.store.read_log("runs"):
            self.conn.execute(
                "INSERT INTO runs (source, capability, target, started_at, finished_at, status, artifacts, records, unmapped, errors, error) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (r["source"], r["capability"], r.get("target", "all"), r["started_at"], r.get("finished_at"), r["status"],
                 r.get("fetches", 0), r.get("records", 0), 0, r.get("errors", 0), r.get("error")))
        for d in self.store.read_log("backfill"):
            self.conn.execute("""INSERT INTO backfill_ledger (url, since, every_days, source, captures, done_at) VALUES (?,?,?,?,?,?)
                                 ON CONFLICT(url, since, every_days) DO UPDATE SET done_at=MAX(backfill_ledger.done_at, excluded.done_at),
                                   captures=excluded.captures, source=excluded.source""",
                              (d["url"], d["since"], int(d["every_days"]), d.get("source"), d.get("captures"), d["done_at"]))

    def run(self) -> Report:
        started = time.monotonic()
        entries = list(self.store.entries()) if self.store else []
        self.owner()
        if self.store:
            self.legacy(entries)
            self.raws(entries)
        self.finish()
        self.logs()
        self.conn.commit()
        self.report.seconds = time.monotonic() - started
        return self.report

    def finish(self) -> None:
        """Everything after reading: derivatives, cars, matching, spans."""
        gold.backfill_used_spans(self.conn)
        self.derivatives()
        self.cars()
        car_of = self.resolve()
        self.trim_map()
        self.report.sightings = len(self.sightings)
        self.fold(car_of)


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
