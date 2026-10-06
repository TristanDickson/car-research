"""Gold writers: upsert canonical rows from one run's records, and resolve a
source's trim naming to a car id through trim_map."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone

from pipeline.providers.types import ParsedRecord

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


def resolve_car(conn: sqlite3.Connection, site: str, key: str, label: str | None,
                example_url: str | None, now: str) -> tuple[str | None, str]:
    """trim_map lookup → (car_id, status). A miss records an 'unmapped' row (first
    time) and bumps last_seen_at (every time) so the snapshot can list what needs
    mapping. 'ignored' rows are derivatives we deliberately don't track."""
    row = conn.execute(
        "SELECT car_id, status FROM trim_map WHERE source=? AND source_key=?", (site, key)
    ).fetchone()
    if row and row["status"] == "mapped" and row["car_id"]:
        conn.execute("UPDATE trim_map SET last_seen_at=? WHERE source=? AND source_key=?", (now, site, key))
        return row["car_id"], "mapped"
    if row:
        conn.execute("UPDATE trim_map SET last_seen_at=?, label=COALESCE(label, ?), example_url=COALESCE(example_url, ?) "
                     "WHERE source=? AND source_key=?", (now, label, example_url, site, key))
        return None, row["status"]
    conn.execute(
        "INSERT INTO trim_map (source, source_key, car_id, status, label, example_url, first_seen_at, last_seen_at) "
        "VALUES (?,?,NULL,'unmapped',?,?,?,?)",
        (site, key, label, example_url, now, now),
    )
    return None, "unmapped"


def write(conn: sqlite3.Connection, source: str, kinds: tuple[str, ...],
          records: dict[str, list[tuple[int, ParsedRecord]]], run_id: int | None, now: str | None = None) -> int:
    now = now or _now()
    written = 0

    for artifact_id, rec in records.get("car", []):
        r = rec.row
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
        fp = fingerprint(r)
        latest = conn.execute(
            "SELECT id, observed_at, confirmed_at, present, fingerprint FROM offer_observations "
            "WHERE offer_key=? ORDER BY observed_at DESC, id DESC LIMIT 1", (r["offer_key"],)
        ).fetchone()
        # An unchanged re-sighting after the last one: extend confirmed_at rather than
        # adding a row. History then holds one row per distinct state, each with the
        # span over which it was seen.
        if (latest and latest["present"] and int(r.get("present", 1)) == 1 and latest["fingerprint"] == fp
                and r["observed_at"] >= latest["observed_at"]):
            conn.execute("UPDATE offer_observations SET confirmed_at=?, run_id=COALESCE(?, run_id) WHERE id=?",
                         (r["observed_at"], run_id, latest["id"]))
            written += 1
            continue
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
        written += 1

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
