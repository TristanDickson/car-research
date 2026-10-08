"""Gold writers: upsert canonical rows from one run's records, and resolve a
source's trim naming to a car id through trim_map."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone

from pipeline.providers.types import ParsedRecord
from pipeline.services import autocars, match, resolve

PRICE_FIELDS = (
    "vehicle_price", "monthly_payment", "apr", "gfv", "customer_deposit",
    "manufacturer_contribution", "num_payments", "term_months", "initial_rental",
    "monthly_rental", "num_rentals", "fees_gbp", "annual_mileage",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _dump(row: dict) -> str:
    return json.dumps(row, ensure_ascii=False, sort_keys=True)


def fingerprint(row: dict) -> str:
    return hashlib.sha1(_dump({k: row.get(k) for k in PRICE_FIELDS}).encode()).hexdigest()[:16]


def _is_auto(conn: sqlite3.Connection, car_id: str) -> bool:
    row = conn.execute("SELECT payload FROM cars WHERE id=?", (car_id,)).fetchone()
    return bool(row) and bool(json.loads(row["payload"]).get("auto"))


def _touch_trim_map(conn: sqlite3.Connection, site: str, key: str, car_id: str | None, status: str,
                    label: str | None, example_url: str | None, now: str, note: str | None = None,
                    method: str | None = None, evidence: str | None = None, name_key: str | None = None) -> None:
    conn.execute(
        """INSERT INTO trim_map (source, source_key, car_id, status, label, example_url, note, first_seen_at, last_seen_at,
             method, evidence, name_key)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(source, source_key) DO UPDATE SET last_seen_at=excluded.last_seen_at,
             label=COALESCE(trim_map.label, excluded.label), example_url=COALESCE(trim_map.example_url, excluded.example_url),
             car_id=CASE WHEN trim_map.status='mapped' THEN trim_map.car_id ELSE excluded.car_id END,
             status=CASE WHEN trim_map.status='mapped' THEN trim_map.status ELSE excluded.status END,
             method=CASE WHEN trim_map.status='mapped' THEN COALESCE(trim_map.method, 'manual') ELSE excluded.method END,
             evidence=CASE WHEN trim_map.status='mapped' THEN trim_map.evidence ELSE excluded.evidence END,
             name_key=COALESCE(excluded.name_key, trim_map.name_key)""",
        (site, key, car_id, status, label, example_url, note, now, now, method, evidence, name_key),
    )


_MODEL_NOISE = {"electric", "electrified", "hatchback", "estate", "saloon", "suv", "mpv", "coupe", "ev", "e-tech", "hatch",
                "5dr", "4dr", "sportback", "fastback", "gran", "tourer", "touring", "shooting", "brake", "cabrio", "convertible"}


def _model_norm(s: str | None) -> str:
    words = [w.lstrip("0") or "0" if w.isdigit() else w   # 'Ora 03' is 'Ora 3'
             for w in (s or "").lower().replace("-", " ").split() if w not in _MODEL_NOISE]
    return " ".join(words)


def _model_agrees(wanted: str | None, car: dict) -> bool:
    """'Kona Electric' / 'Kona', 'Ioniq 3 Hatchback' / 'Ioniq 3', 'PV5' / 'PV5
    Passenger' agree; 'Ioniq 3' / 'Ioniq 5' do not."""
    a = _model_norm(wanted)
    if not a:
        return True
    for b in (_model_norm(car.get("model")), _model_norm((car.get("model_slug") or "").replace("-", " "))):
        if b and (a == b or a.startswith(b + " ") or b.startswith(a + " ")):
            return True
    return False


def _auto_candidates(conn: sqlite3.Connection, make: str | None, model: str | None) -> list[dict]:
    """Generated cars of one make + model, for the derivative-text matcher."""
    if not make:
        return []
    out = []
    for r in conn.execute("SELECT payload FROM cars WHERE lower(make)=?", ((make or "").lower(),)):
        p = json.loads(r["payload"])
        if p.get("auto") and _model_agrees(model, p):
            out.append(p)
    return out


def resolve_car(conn: sqlite3.Connection, site: str, key: str, label: str | None,
                example_url: str | None, now: str, record_miss: bool = True,
                ref: dict | None = None) -> tuple[str | None, str]:
    """A source's naming → (car_id, status).

    1. trim_map says 'mapped' → the hand-curated car.
    2. Otherwise a generated car: for a Carwow CAP id the car carwow-cap:<id>
       (made here from the record's stub when the specification page has not
       produced one); for a broker's derivative text, the one generated car of
       that make + model that services/resolve.py picks (status 'auto', with the
       method and evidence on the row; 'conflict' when twins cannot be told apart).
    3. Otherwise the old behaviour: an 'unmapped' row the first time (bumped
       every time) so the snapshot can list what needs a human; 'ignored' rows
       are derivatives deliberately left out of the hand-curated set."""
    ref = ref or {}
    row = conn.execute(
        "SELECT car_id, status FROM trim_map WHERE source=? AND source_key=?", (site, key)
    ).fetchone()
    if row and row["status"] == "mapped" and row["car_id"]:
        conn.execute("UPDATE trim_map SET last_seen_at=? WHERE source=? AND source_key=?", (now, site, key))
        return row["car_id"], "mapped"

    auto_id, method, evidence, nkey = None, None, None, None
    if site == "carwow-cap":
        cid = autocars.auto_id(key)
        if conn.execute("SELECT 1 FROM cars WHERE id=?", (cid,)).fetchone():
            auto_id, method = cid, "cap-id"
        elif ref.get("stub"):
            ensure_auto_car(conn, autocars.from_stub(ref["stub"]), ref.get("provider") or site, None, None, now)
            auto_id, method = cid, "stub"
    elif ref.get("make"):
        res = resolve.choose(ref, _auto_candidates(conn, ref.get("make"), ref.get("model")), conn)
        method, evidence, nkey = res.method, resolve.dump_evidence(res.evidence), resolve.name_key(ref.get("derivative") or label)
        if res.car_id:
            auto_id = res.car_id
            _apply_bracket_facts(conn, auto_id, res.brackets, now)
        elif res.method == "conflict":
            _touch_trim_map(conn, site, key, None, "conflict", label, example_url, now, method=method, evidence=evidence, name_key=nkey)
            return None, "conflict"
    if auto_id:
        _touch_trim_map(conn, site, key, auto_id, "auto", label, example_url, now, method=method, evidence=evidence, name_key=nkey)
        return auto_id, "auto"

    if row:
        conn.execute("UPDATE trim_map SET last_seen_at=?, label=COALESCE(label, ?), example_url=COALESCE(example_url, ?), "
                     "method=COALESCE(?, method), evidence=COALESCE(?, evidence), name_key=COALESCE(?, name_key) "
                     "WHERE source=? AND source_key=?", (now, label, example_url, method, evidence, nkey, site, key))
        return None, row["status"]
    if not record_miss:
        return None, "unknown"
    conn.execute(
        "INSERT INTO trim_map (source, source_key, car_id, status, label, example_url, first_seen_at, last_seen_at, method, evidence, name_key) "
        "VALUES (?,?,NULL,'unmapped',?,?,?,?,?,?,?)",
        (site, key, label, example_url, now, now, method, evidence, nkey),
    )
    return None, "unmapped"


def _apply_bracket_facts(conn: sqlite3.Connection, car_id: str, br: list[str], now: str) -> None:
    """A broker's '[Heat Pump]' / '[7 seat]' names something about the generated
    derivative that Carwow's pages never print: write it onto the car."""
    if not br:
        return
    row = conn.execute("SELECT payload, source FROM cars WHERE id=?", (car_id,)).fetchone()
    if not row:
        return
    car = json.loads(row["payload"])
    facts = resolve.facts_from_brackets(car, br)
    if facts and any(car.get(k) != v for k, v in facts.items()):
        _upsert_car(conn, {**car, **facts}, row["source"], None, now)


def _upsert_car(conn: sqlite3.Connection, r: dict, source: str, artifact_id: int | None, now: str) -> None:
    conn.execute(
        """INSERT INTO cars (id, make, model, trim, model_year, seats, battery_kwh, wltp_range_mi,
             width_mm, list_price_gbp, grant_gbp, heat_pump, internal_v2l, payload, source, artifact_id, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET make=excluded.make, model=excluded.model, trim=excluded.trim,
             model_year=excluded.model_year, seats=excluded.seats, battery_kwh=excluded.battery_kwh,
             wltp_range_mi=excluded.wltp_range_mi, width_mm=excluded.width_mm,
             list_price_gbp=excluded.list_price_gbp, grant_gbp=excluded.grant_gbp,
             heat_pump=excluded.heat_pump, internal_v2l=excluded.internal_v2l, payload=excluded.payload,
             source=excluded.source, artifact_id=excluded.artifact_id, updated_at=excluded.updated_at""",
        (
            r["id"], r["make"], r["model"], r.get("trim"), r.get("model_year"), r.get("seats"),
            r.get("battery_kwh"), r.get("wltp_range_mi"), r.get("width_mm"), r.get("list_price_gbp"),
            r.get("grant_gbp"), r.get("heat_pump"), r.get("internal_v2l"), _dump(r), source, artifact_id, now,
        ),
    )


def ensure_auto_car(conn: sqlite3.Connection, car: dict, source: str, artifact_id: int | None,
                    run_id: int | None, now: str) -> bool:
    """Write a generated car unless a hand-curated one owns the id. A spec-built
    car replaces a stub (and an older spec-built one); a stub never replaces
    anything. Returns True if the row was written."""
    row = conn.execute("SELECT payload FROM cars WHERE id=?", (car["id"],)).fetchone()
    if row:
        existing = json.loads(row["payload"])
        if not existing.get("auto"):
            return False
        if car.get("source_kind") == "stub":
            return False
    _upsert_car(conn, car, source, artifact_id, now)
    return True


def upsert_derivative(conn: sqlite3.Connection, r: dict, source: str, artifact_id: int | None, run_id: int | None, now: str,
                      first_seen_at: str | None = None, last_seen_at: str | None = None) -> None:
    """A row of the registry, and a stub car for a derivative nothing else described
    (a spec-built car keeps its place; a stub never replaces anything)."""
    conn.execute(
        """INSERT INTO derivatives (cap_id, make_slug, model_slug, name, trim, engine, rrp, version_date, payload,
             first_seen_at, last_seen_at, artifact_id, run_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(cap_id) DO UPDATE SET
             make_slug=excluded.make_slug, model_slug=excluded.model_slug, name=excluded.name, trim=excluded.trim, engine=excluded.engine,
             rrp=COALESCE(excluded.rrp, derivatives.rrp), version_date=COALESCE(excluded.version_date, derivatives.version_date),
             payload=excluded.payload, first_seen_at=MIN(derivatives.first_seen_at, excluded.first_seen_at),
             last_seen_at=MAX(derivatives.last_seen_at, excluded.last_seen_at), artifact_id=excluded.artifact_id, run_id=excluded.run_id""",
        (r["cap_id"], r["make_slug"], r["model_slug"], r["name"], r.get("trim"), r.get("engine"), r.get("rrp"), r.get("version_date"),
         _dump(r), first_seen_at or now, last_seen_at or now, artifact_id, run_id),
    )
    stub = {"cap_id": r["cap_id"], "make": r.get("make") or r["make_slug"], "make_slug": r["make_slug"], "model": r.get("model") or r["model_slug"],
            "model_slug": r["model_slug"], "trim": r.get("trim"), "engine": r.get("engine"), "rrp": r.get("rrp"), "version_date": r.get("version_date")}
    ensure_auto_car(conn, autocars.from_stub(stub), source, artifact_id, run_id, now)


def upsert_options(conn: sqlite3.Connection, r: dict, artifact_id: int | None, run_id: int | None, now: str,
                   first_seen_at: str | None = None, last_seen_at: str | None = None) -> None:
    conn.execute(
        """INSERT INTO options (cap_id, payload, first_seen_at, last_seen_at, artifact_id, run_id) VALUES (?,?,?,?,?,?)
           ON CONFLICT(cap_id) DO UPDATE SET payload=excluded.payload,
             first_seen_at=MIN(options.first_seen_at, excluded.first_seen_at), last_seen_at=MAX(options.last_seen_at, excluded.last_seen_at),
             artifact_id=excluded.artifact_id, run_id=excluded.run_id""",
        (r["cap_id"], _dump(r), first_seen_at or now, last_seen_at or now, artifact_id, run_id),
    )


def prune_auto_cars(conn: sqlite3.Connection) -> int:
    """Drop generated cars nothing refers to any more (their derivative was mapped
    to a hand-curated car and no observation or spec still points at them)."""
    rows = conn.execute(
        """SELECT id FROM cars WHERE json_extract(payload, '$.auto') = 1
             AND id NOT IN (SELECT car_id FROM offer_observations)
             AND id NOT IN (SELECT car_id FROM specs WHERE car_id IS NOT NULL)
             AND id NOT IN (SELECT car_id FROM trim_map WHERE car_id IS NOT NULL AND status='mapped')
             AND id NOT IN (SELECT 'carwow-cap:' || cap_id FROM derivatives)"""
    ).fetchall()
    for r in rows:
        conn.execute("DELETE FROM trim_map WHERE car_id=? AND status='auto'", (r["id"],))
        conn.execute("DELETE FROM cars WHERE id=?", (r["id"],))
    return len(rows)


def _span_end(o: sqlite3.Row) -> str:
    return o["confirmed_at"] or o["observed_at"]


def _merge_sighting(conn: sqlite3.Connection, r: dict, fp: str, run_id: int | None) -> bool:
    """Fold an unchanged sighting into the span it belongs to instead of adding a row.

    History holds one row per distinct state, each with the span [observed_at,
    confirmed_at] over which it was seen. A sighting at time t with the same
    price-bearing fields as the span before it extends that span forward; one
    matching the span after it (a backfilled older copy of the page) moves that
    span's start back; one that bridges two matching spans merges them. Anything
    else (a new price, a 'gone', a corrected payload at the same instant) is a
    row of its own. Returns True if the sighting was absorbed."""
    if int(r.get("present", 1)) != 1:
        return False
    t, key = r["observed_at"], r["offer_key"]
    prev = conn.execute(
        "SELECT id, observed_at, confirmed_at, present, fingerprint FROM offer_observations "
        "WHERE offer_key=? AND observed_at<=? ORDER BY observed_at DESC, id DESC LIMIT 1", (key, t)
    ).fetchone()
    nxt = conn.execute(
        "SELECT id, observed_at, confirmed_at, present, fingerprint FROM offer_observations "
        "WHERE offer_key=? AND observed_at>? ORDER BY observed_at ASC, id ASC LIMIT 1", (key, t)
    ).fetchone()
    prev_same = bool(prev and prev["present"] and prev["fingerprint"] == fp)
    next_same = bool(nxt and nxt["present"] and nxt["fingerprint"] == fp)
    if prev_same:
        end = max(_span_end(prev), t)
        if next_same:
            end = max(end, _span_end(nxt))
            conn.execute("DELETE FROM offer_observations WHERE id=?", (nxt["id"],))
        conn.execute("UPDATE offer_observations SET confirmed_at=?, run_id=COALESCE(?, run_id) WHERE id=?",
                     (end, run_id, prev["id"]))
        return True
    if next_same:
        # The span starts earlier; its old start becomes a confirmation if it had none.
        conn.execute("UPDATE offer_observations SET observed_at=?, confirmed_at=COALESCE(confirmed_at, observed_at) WHERE id=?",
                     (t, nxt["id"]))
        return True
    if prev and prev["present"] and prev["confirmed_at"] and prev["confirmed_at"] > t:
        # A different price seen inside a span we assumed unbroken: the span was
        # seen at its start and at its end, so split it there and let the caller
        # insert the contradicting sighting between.
        conn.execute(
            """INSERT INTO offer_observations (offer_key, car_id, source, observed_at, confirmed_at, present, finance_type,
                 status, verification, seller, vehicle_price, monthly_payment, apr, gfv, fingerprint, payload, artifact_id, run_id)
               SELECT offer_key, car_id, source, confirmed_at, NULL, present, finance_type, status, verification, seller,
                 vehicle_price, monthly_payment, apr, gfv, fingerprint, payload, artifact_id, run_id
               FROM offer_observations WHERE id=?""", (prev["id"],))
        conn.execute("UPDATE offer_observations SET confirmed_at=NULL WHERE id=?", (prev["id"],))
    return False


def _insert_observation(conn: sqlite3.Connection, r: dict, source: str, fp: str,
                        artifact_id: int | None, run_id: int | None) -> None:
    conn.execute(
        """INSERT INTO offer_observations (offer_key, car_id, source, observed_at, present, finance_type, status,
             verification, seller, vehicle_price, monthly_payment, apr, gfv, fingerprint, payload, artifact_id, run_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(offer_key, observed_at, source) DO UPDATE SET car_id=excluded.car_id, present=excluded.present,
             finance_type=excluded.finance_type, status=excluded.status, verification=excluded.verification,
             seller=excluded.seller, vehicle_price=excluded.vehicle_price, monthly_payment=excluded.monthly_payment,
             apr=excluded.apr, gfv=excluded.gfv, fingerprint=excluded.fingerprint, payload=excluded.payload,
             artifact_id=excluded.artifact_id, run_id=excluded.run_id""",
        (
            r["offer_key"], r["car_id"], source, r["observed_at"], int(r.get("present", 1)), r["finance_type"],
            r["status"], r.get("verification"), r.get("dealer") or r.get("source"), r.get("vehicle_price"),
            r.get("monthly_payment"), r.get("apr"), r.get("gfv"), fp, _dump(r), artifact_id, run_id,
        ),
    )


def _merge_used_sighting(conn: sqlite3.Connection, key: str, source: str, price: float | None, mileage: int | None,
                         present: bool, now: str, run_id: int | None) -> None:
    """The listing's asking price as spans: the same price seen again extends
    the open span; a new price, or the listing going, opens a new one."""
    last = conn.execute(
        "SELECT id, price_gbp, present, observed_at FROM used_observations WHERE listing_key=? ORDER BY observed_at DESC, id DESC LIMIT 1",
        (key,),
    ).fetchone()
    if last and bool(last["present"]) == present and (not present or last["price_gbp"] == price):
        conn.execute("UPDATE used_observations SET confirmed_at=?, mileage=COALESCE(?, mileage), run_id=COALESCE(?, run_id) WHERE id=?",
                     (now, mileage, run_id, last["id"]))
        return
    if last and last["observed_at"] == now:
        conn.execute("UPDATE used_observations SET price_gbp=?, mileage=?, present=?, confirmed_at=? WHERE id=?",
                     (price, mileage, int(present), now, last["id"]))
        return
    conn.execute(
        "INSERT INTO used_observations (listing_key, source, price_gbp, mileage, observed_at, confirmed_at, present, run_id) VALUES (?,?,?,?,?,?,?,?)",
        (key, source, price, mileage, now, now, int(present), run_id),
    )


def backfill_used_spans(conn: sqlite3.Connection) -> int:
    """A span for every listing that has none yet (stock recorded before spans
    existed): its current price from first to last sighting. Idempotent."""
    rows = conn.execute(
        """SELECT l.listing_key, l.source, l.price_gbp, l.mileage, l.first_seen_at, l.last_seen_at, l.present
             FROM used_listings l WHERE NOT EXISTS (SELECT 1 FROM used_observations o WHERE o.listing_key=l.listing_key)"""
    ).fetchall()
    for r in rows:
        conn.execute(
            "INSERT INTO used_observations (listing_key, source, price_gbp, mileage, observed_at, confirmed_at, present) VALUES (?,?,?,?,?,?,1)",
            (r["listing_key"], r["source"], r["price_gbp"], r["mileage"], r["first_seen_at"], r["last_seen_at"]),
        )
        if not r["present"]:
            # Gone since its last sighting; a car seen once gets its closing row a second later.
            gone_at = r["last_seen_at"]
            if gone_at == r["first_seen_at"]:
                gone_at = (datetime.fromisoformat(gone_at) + timedelta(seconds=1)).isoformat(timespec="seconds")
            conn.execute(
                "INSERT INTO used_observations (listing_key, source, price_gbp, mileage, observed_at, confirmed_at, present) VALUES (?,?,?,?,?,?,0)",
                (r["listing_key"], r["source"], r["price_gbp"], r["mileage"], gone_at, gone_at),
            )
    return len(rows)


def write(conn: sqlite3.Connection, source: str, kinds: tuple[str, ...],
          records: dict[str, list[tuple[int, ParsedRecord]]], run_id: int | None, now: str | None = None) -> int:
    now = now or _now()
    written = 0

    for artifact_id, rec in records.get("car", []):
        _upsert_car(conn, rec.row, source, artifact_id, now)
        written += 1

    for artifact_id, rec in records.get("model", []):
        r = rec.row
        conn.execute(
            """INSERT INTO models (slug, make, model, make_name, model_name, electric, has_deals, has_specs, source, payload,
                 first_seen_at, last_seen_at, artifact_id, run_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(slug) DO UPDATE SET
                 make_name=COALESCE(excluded.make_name, models.make_name), model_name=COALESCE(excluded.model_name, models.model_name),
                 electric=COALESCE(excluded.electric, models.electric), has_deals=COALESCE(excluded.has_deals, models.has_deals),
                 has_specs=COALESCE(excluded.has_specs, models.has_specs), source=excluded.source,
                 last_seen_at=excluded.last_seen_at, artifact_id=excluded.artifact_id, run_id=excluded.run_id""",
            (r["slug"], r["make"], r["model"], r.get("make_name"), r.get("model_name"), r.get("electric"), r.get("has_deals"),
             r.get("has_specs"), source, _dump(r), now, now, artifact_id, run_id),
        )
        written += 1

    for artifact_id, rec in records.get("trim_map", []):
        r = rec.row
        conn.execute(
            """INSERT INTO trim_map (source, source_key, car_id, status, label, example_url, note, first_seen_at, last_seen_at)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(source, source_key) DO UPDATE SET car_id=excluded.car_id, status=excluded.status,
                 note=excluded.note, last_seen_at=excluded.last_seen_at""",
            (r["source"], r["source_key"], r.get("car_id"), r.get("status", "mapped" if r.get("car_id") else "ignored"),
             r.get("label"), r.get("example_url"), r.get("note"), now, now),
        )
        written += 1

    for artifact_id, rec in records.get("offer", []):
        r = rec.row
        # An offer key names one derivative at its source, so when resolution now
        # puts it on a different car (a better rule, a promoted hand-curated car)
        # its whole sighting history moves with it.
        conn.execute("UPDATE offer_observations SET car_id=? WHERE offer_key=? AND car_id<>?",
                     (r["car_id"], r["offer_key"], r["car_id"]))
        if _merge_sighting(conn, r, fingerprint(r), run_id):
            written += 1
            continue
        _insert_observation(conn, r, source, fingerprint(r), artifact_id, run_id)
        written += 1

    for artifact_id, rec in records.get("spec", []):
        r = rec.row
        if r.get("cap_id") and r["spec_key"].startswith("carwow-cap:") and r.get("car_id") in (None, autocars.auto_id(r["cap_id"])):
            # Nobody curates this derivative: it becomes a generated car (a
            # spec-built one replaces the stub a deals page may have left, and
            # refreshes an older spec-built one).
            car = autocars.from_spec(r)
            if ensure_auto_car(conn, car, source, artifact_id, run_id, now) or _is_auto(conn, car["id"]):
                r["car_id"] = car["id"]
                _touch_trim_map(conn, "carwow-cap", r["cap_id"], car["id"], "auto",
                                (r.get("car_ref") or {}).get("label"), r.get("source_url"), now)
        fp = hashlib.sha1(_dump({k: r.get(k) for k in ("features", "flags", "numbers", "rrp", "trim", "variant")}).encode()).hexdigest()[:16]
        conn.execute(
            """INSERT INTO specs (spec_key, source, make, model, trim, variant, cap_id, version_date, car_id, image_url,
                 fingerprint, payload, first_seen_at, last_seen_at, changed_at, artifact_id, run_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(spec_key) DO UPDATE SET
                 source=excluded.source, make=excluded.make, model=excluded.model, trim=excluded.trim, variant=excluded.variant,
                 cap_id=excluded.cap_id, version_date=excluded.version_date, car_id=COALESCE(excluded.car_id, specs.car_id),
                 image_url=COALESCE(excluded.image_url, specs.image_url),
                 changed_at=CASE WHEN specs.fingerprint IS NOT excluded.fingerprint THEN excluded.last_seen_at ELSE specs.changed_at END,
                 fingerprint=excluded.fingerprint, payload=excluded.payload, last_seen_at=excluded.last_seen_at,
                 artifact_id=excluded.artifact_id, run_id=excluded.run_id""",
            (r["spec_key"], source, r.get("make"), r.get("model"), r.get("trim"), r.get("variant"), r.get("cap_id"),
             r.get("version_date"), r.get("car_id"), r.get("image_url"), fp, _dump(r), now, now, now, artifact_id, run_id),
        )
        written += 1

    for artifact_id, rec in records.get("derivative", []):
        upsert_derivative(conn, rec.row, source, artifact_id, run_id, now)
        written += 1

    for artifact_id, rec in records.get("options", []):
        upsert_options(conn, rec.row, artifact_id, run_id, now)
        written += 1

    used_seen: dict[str, set[str]] = {}
    for artifact_id, rec in records.get("used", []):
        r = rec.row
        car_id = None
        ref = r.get("car_ref") or {}
        if ref.get("make"):
            # Link to a derivative where the text names one; never a trim-map row (stock is not an offer).
            res = resolve.choose(ref, _auto_candidates(conn, ref.get("make"), ref.get("model")), conn)
            car_id = res.car_id
        conn.execute(
            """INSERT INTO used_listings (listing_key, source, make, make_slug, model, model_slug, car_id, price_gbp, year, mileage,
                 present, payload, first_seen_at, last_seen_at, artifact_id, run_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,1,?,?,?,?,?)
               ON CONFLICT(listing_key) DO UPDATE SET price_gbp=excluded.price_gbp, mileage=excluded.mileage, present=1,
                 car_id=COALESCE(excluded.car_id, used_listings.car_id), payload=excluded.payload,
                 last_seen_at=excluded.last_seen_at, artifact_id=excluded.artifact_id, run_id=excluded.run_id""",
            (r["listing_key"], source, r.get("make"), r.get("make_slug"), r.get("model"), r.get("model_slug"), car_id,
             r.get("price_gbp"), r.get("year"), r.get("mileage"), _dump(r), now, now, artifact_id, run_id),
        )
        _merge_used_sighting(conn, r["listing_key"], source, r.get("price_gbp"), r.get("mileage"), True, now, run_id)
        used_seen.setdefault(r.get("listing_url") or "", set()).add(r["listing_key"])
        written += 1
    for listing_url, keys in used_seen.items():
        # A listing missing from the page it came from (a model's cards on Carwow,
        # a make's stock on cinch, the whole electric listing on Motorpoint) has
        # been sold or withdrawn; another source's, or a page not fetched this
        # run, is untouched.
        marks = ",".join("?" * len(keys))
        where = f"""source=? AND COALESCE(json_extract(payload, '$.listing_url'), '')=? AND present=1
                    AND listing_key NOT IN ({marks})"""
        gone = conn.execute(f"SELECT listing_key, price_gbp, mileage FROM used_listings WHERE {where}", (source, listing_url, *keys)).fetchall()
        conn.execute(f"UPDATE used_listings SET present=0 WHERE {where}", (source, listing_url, *keys))
        for g in gone:
            _merge_used_sighting(conn, g["listing_key"], source, g["price_gbp"], g["mileage"], False, now, run_id)

    for artifact_id, rec in records.get("requirements", []):
        r = rec.row
        conn.execute(
            """INSERT INTO requirements (id, as_of, payload, source, artifact_id, updated_at) VALUES (1,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET as_of=excluded.as_of, payload=excluded.payload, source=excluded.source,
                 artifact_id=excluded.artifact_id, updated_at=excluded.updated_at""",
            (r.get("as_of"), _dump(r), source, artifact_id, now),
        )
        written += 1
    return written
