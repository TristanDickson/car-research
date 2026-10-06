"""Gold writers: replace a provider's canonical rows from one run's records."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from pipeline.providers.types import ParsedRecord


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _dump(row: dict) -> str:
    return json.dumps(row, ensure_ascii=False, sort_keys=True)


def replace(
    conn: sqlite3.Connection,
    source: str,
    kinds: tuple[str, ...],
    records: dict[str, list[tuple[int, ParsedRecord]]],
    now: str | None = None,
) -> int:
    """Delete this provider's Gold rows for `kinds` and insert the run's records.

    `records` maps kind → [(artifact_id, record)]. Deals are deleted before cars
    and inserted after them so the FK holds throughout.
    """
    now = now or _now()
    written = 0
    if "deal" in kinds:
        conn.execute("DELETE FROM deals WHERE source = ?", (source,))
    if "car" in kinds:
        conn.execute("DELETE FROM cars WHERE source = ?", (source,))

    for artifact_id, rec in records.get("car", []):
        r = rec.row
        conn.execute(
            """INSERT INTO cars (id, make, model, trim, model_year, seats, battery_kwh,
                 wltp_range_mi, width_mm, list_price_gbp, grant_gbp, heat_pump, internal_v2l,
                 payload, source, artifact_id, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                r["id"], r["make"], r["model"], r.get("trim"), r.get("model_year"),
                r.get("seats"), r.get("battery_kwh"), r.get("wltp_range_mi"), r.get("width_mm"),
                r.get("list_price_gbp"), r.get("grant_gbp"), r.get("heat_pump"),
                r.get("internal_v2l"), _dump(r), source, artifact_id, now,
            ),
        )
        written += 1

    for artifact_id, rec in records.get("deal", []):
        r = rec.row
        conn.execute(
            """INSERT INTO deals (id, car_id, captured_at, finance_type, status, verification,
                 seller_source, vehicle_price, monthly_payment, apr, gfv,
                 payload, source, artifact_id, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                r["id"], r["car_id"], r.get("captured_at"), r["finance_type"], r["status"],
                r.get("verification"), r.get("source"), r.get("vehicle_price"),
                r.get("monthly_payment"), r.get("apr"), r.get("gfv"),
                _dump(r), source, artifact_id, now,
            ),
        )
        written += 1

    for artifact_id, rec in records.get("requirements", []):
        r = rec.row
        conn.execute(
            """INSERT INTO requirements (id, as_of, payload, source, artifact_id, updated_at)
               VALUES (1,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET as_of=excluded.as_of, payload=excluded.payload,
                 source=excluded.source, artifact_id=excluded.artifact_id,
                 updated_at=excluded.updated_at""",
            (r.get("as_of"), _dump(r), source, artifact_id, now),
        )
        written += 1
    return written
