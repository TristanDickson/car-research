"""The observation log as committed text, so a fresh database (CI, a new
machine) carries the full sighting history without the bronze artifacts.

data/history/observations.jsonl: one line per offer_observations row, sorted,
rewritten on every export. Import upserts by (offer_key, observed_at, source).
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from pipeline.db import ROOT

DEFAULT_PATH = ROOT / "data" / "history" / "observations.jsonl"
SPECS_PATH = ROOT / "data" / "history" / "specs.jsonl"
SPEC_COLUMNS = ("spec_key", "source", "make", "model", "trim", "variant", "cap_id", "version_date", "car_id", "image_url",
                "fingerprint", "payload", "first_seen_at", "last_seen_at", "changed_at")
COLUMNS = ("offer_key", "car_id", "source", "observed_at", "confirmed_at", "present", "finance_type", "status",
           "verification", "seller", "vehicle_price", "monthly_payment", "apr", "gfv", "fingerprint", "payload")


def export_history(conn: sqlite3.Connection, path: Path | str = DEFAULT_PATH, source: str | None = None) -> int:
    """Write every observation (or only one provider's, with `source`) as JSONL."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    where, params = ("WHERE source=?", (source,)) if source else ("", ())
    rows = conn.execute(
        f"SELECT {', '.join(COLUMNS)} FROM offer_observations {where} ORDER BY offer_key, observed_at, source", params
    ).fetchall()
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            d = {k: r[k] for k in COLUMNS}
            d["payload"] = json.loads(d["payload"])
            f.write(json.dumps(d, ensure_ascii=False, sort_keys=True) + "\n")
    return len(rows)


def import_history(conn: sqlite3.Connection, path: Path | str = DEFAULT_PATH, replace_source: str | None = None) -> int:
    """Upsert the file's rows. With `replace_source`, that provider's existing rows
    are dropped first so the file is the whole truth for it (how the chunked
    backfill merges one job's result per provider)."""
    path = Path(path)
    if not path.exists():
        return 0
    if replace_source:
        conn.execute("DELETE FROM offer_observations WHERE source=?", (replace_source,))
    n = 0
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            # Only rows whose car exists can be loaded (FK); the seed runs first.
            if not conn.execute("SELECT 1 FROM cars WHERE id=?", (d["car_id"],)).fetchone():
                continue
            conn.execute(
                """INSERT INTO offer_observations (offer_key, car_id, source, observed_at, confirmed_at, present,
                     finance_type, status, verification, seller, vehicle_price, monthly_payment, apr, gfv,
                     fingerprint, payload)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(offer_key, observed_at, source) DO UPDATE SET
                     confirmed_at=COALESCE(excluded.confirmed_at, offer_observations.confirmed_at),
                     present=excluded.present, status=excluded.status, payload=excluded.payload,
                     fingerprint=excluded.fingerprint, car_id=excluded.car_id""",
                (d["offer_key"], d["car_id"], d["source"], d["observed_at"], d.get("confirmed_at"), int(d["present"]),
                 d["finance_type"], d["status"], d.get("verification"), d.get("seller"), d.get("vehicle_price"),
                 d.get("monthly_payment"), d.get("apr"), d.get("gfv"), d.get("fingerprint"),
                 json.dumps(d["payload"], ensure_ascii=False, sort_keys=True)),
            )
            n += 1
    conn.commit()
    return n


def export_specs(conn: sqlite3.Connection, path: Path | str = SPECS_PATH) -> int:
    """Every spec row as JSONL, so CI and a fresh clone carry the scraped equipment too."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = conn.execute(f"SELECT {', '.join(SPEC_COLUMNS)} FROM specs ORDER BY spec_key").fetchall()
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            d = {k: r[k] for k in SPEC_COLUMNS}
            d["payload"] = json.loads(d["payload"])
            f.write(json.dumps(d, ensure_ascii=False, sort_keys=True) + "\n")
    return len(rows)


def import_specs(conn: sqlite3.Connection, path: Path | str = SPECS_PATH) -> int:
    path = Path(path)
    if not path.exists():
        return 0
    n = 0
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            car_id = d.get("car_id")
            if car_id and not conn.execute("SELECT 1 FROM cars WHERE id=?", (car_id,)).fetchone():
                car_id = None
            conn.execute(
                """INSERT INTO specs (spec_key, source, make, model, trim, variant, cap_id, version_date, car_id, image_url,
                     fingerprint, payload, first_seen_at, last_seen_at, changed_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(spec_key) DO UPDATE SET
                     first_seen_at=MIN(specs.first_seen_at, excluded.first_seen_at),
                     last_seen_at=MAX(specs.last_seen_at, excluded.last_seen_at),
                     changed_at=COALESCE(excluded.changed_at, specs.changed_at),
                     payload=CASE WHEN excluded.last_seen_at >= specs.last_seen_at THEN excluded.payload ELSE specs.payload END,
                     fingerprint=CASE WHEN excluded.last_seen_at >= specs.last_seen_at THEN excluded.fingerprint ELSE specs.fingerprint END,
                     car_id=COALESCE(excluded.car_id, specs.car_id), image_url=COALESCE(excluded.image_url, specs.image_url)""",
                (d["spec_key"], d["source"], d.get("make"), d.get("model"), d.get("trim"), d.get("variant"), d.get("cap_id"),
                 d.get("version_date"), car_id, d.get("image_url"), d.get("fingerprint"),
                 json.dumps(d["payload"], ensure_ascii=False, sort_keys=True), d["first_seen_at"], d["last_seen_at"], d.get("changed_at")),
            )
            n += 1
    conn.commit()
    return n
