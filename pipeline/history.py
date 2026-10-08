"""The observation log as committed text, so a fresh database (CI, a new
machine) carries the full sighting history without the bronze artifacts.

data/history/observations.jsonl: one line per offer_observations row, sorted,
rewritten on every export. Import upserts by (offer_key, observed_at, source).
data/history/specs.jsonl and models.jsonl carry the scraped specs and the
catalogue the same way; resolutions.jsonl the broker rows' resolution (which
derivative, how, with what evidence) and backfill.jsonl the backfill ledger.
Replay order matters: models, then specs (which make the generated cars), then
the derivative registry (derivatives.jsonl: stub cars for what the specs omit),
then observations (whose car must exist), then resolutions (whose car must
exist, and whose brackets are written back onto the generated cars).
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from pipeline import gold
from pipeline.db import ROOT
from pipeline.services import autocars

DEFAULT_PATH = ROOT / "data" / "history" / "observations.jsonl"
SPECS_PATH = ROOT / "data" / "history" / "specs.jsonl"
MODELS_PATH = ROOT / "data" / "history" / "models.jsonl"
LEDGER_PATH = ROOT / "data" / "history" / "backfill.jsonl"
RESOLUTIONS_PATH = ROOT / "data" / "history" / "resolutions.jsonl"
USED_PATH = ROOT / "data" / "history" / "used.jsonl"
USED_OBS_PATH = ROOT / "data" / "history" / "used_observations.jsonl"
DERIVATIVES_PATH = ROOT / "data" / "history" / "derivatives.jsonl"
OPTIONS_PATH = ROOT / "data" / "history" / "options.jsonl"
DERIVATIVE_COLUMNS = ("cap_id", "make_slug", "model_slug", "name", "trim", "engine", "rrp", "version_date", "payload", "first_seen_at", "last_seen_at")
USED_OBS_COLUMNS = ("listing_key", "source", "price_gbp", "mileage", "observed_at", "confirmed_at", "present")
USED_COLUMNS = ("listing_key", "source", "make", "make_slug", "model", "model_slug", "car_id", "price_gbp", "year", "mileage",
                "present", "payload", "first_seen_at", "last_seen_at")
RES_COLUMNS = ("source", "source_key", "car_id", "status", "label", "example_url", "method", "evidence", "name_key",
               "first_seen_at", "last_seen_at")
LEDGER_COLUMNS = ("url", "since", "every_days", "source", "captures", "done_at")
MODEL_COLUMNS = ("slug", "make", "model", "make_name", "model_name", "electric", "has_deals", "has_specs", "source",
                 "payload", "first_seen_at", "last_seen_at")
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
            # Only rows whose car exists can be loaded (FK); the seed and the specs
            # run first. A derivative only a deals page ever printed gets its
            # stub car back from the observation itself.
            if not conn.execute("SELECT 1 FROM cars WHERE id=?", (d["car_id"],)).fetchone():
                stub = ((d.get("payload") or {}).get("car_ref") or {}).get("stub")
                if not (stub and autocars.auto_id(stub.get("cap_id", "")) == d["car_id"]):
                    continue
                gold.ensure_auto_car(conn, autocars.from_stub(stub), d["source"], None, None, d["observed_at"])
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
            payload = d["payload"]
            if not car_id and payload.get("cap_id") and d["spec_key"].startswith("carwow-cap:"):
                # Nobody curates this derivative: regenerate its car from the spec.
                car = autocars.from_spec(payload)
                if gold.ensure_auto_car(conn, car, d["source"], None, None, d["last_seen_at"]):
                    car_id = car["id"]
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


def export_models(conn: sqlite3.Connection, path: Path | str = MODELS_PATH) -> int:
    """The catalogue as JSONL, so an offline refresh knows every model too."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = conn.execute(f"SELECT {', '.join(MODEL_COLUMNS)} FROM models ORDER BY slug").fetchall()
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            d = {k: r[k] for k in MODEL_COLUMNS}
            d["payload"] = json.loads(d["payload"])
            f.write(json.dumps(d, ensure_ascii=False, sort_keys=True) + "\n")
    return len(rows)


def import_models(conn: sqlite3.Connection, path: Path | str = MODELS_PATH) -> int:
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
            conn.execute(
                """INSERT INTO models (slug, make, model, make_name, model_name, electric, has_deals, has_specs, source, payload,
                     first_seen_at, last_seen_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(slug) DO UPDATE SET
                     make_name=COALESCE(excluded.make_name, models.make_name), model_name=COALESCE(excluded.model_name, models.model_name),
                     electric=COALESCE(excluded.electric, models.electric), has_deals=COALESCE(excluded.has_deals, models.has_deals),
                     has_specs=COALESCE(excluded.has_specs, models.has_specs),
                     first_seen_at=MIN(models.first_seen_at, excluded.first_seen_at),
                     last_seen_at=MAX(models.last_seen_at, excluded.last_seen_at)""",
                (d["slug"], d["make"], d["model"], d.get("make_name"), d.get("model_name"), d.get("electric"), d.get("has_deals"),
                 d.get("has_specs"), d["source"], json.dumps(d["payload"], ensure_ascii=False, sort_keys=True),
                 d["first_seen_at"], d["last_seen_at"]),
            )
            n += 1
    conn.commit()
    return n


def export_ledger(conn: sqlite3.Connection, path: Path | str = LEDGER_PATH) -> int:
    """Which pages the Wayback backfill has done (see providers/wayback.py)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = conn.execute(f"SELECT {', '.join(LEDGER_COLUMNS)} FROM backfill_ledger ORDER BY url, since, every_days").fetchall()
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps({k: r[k] for k in LEDGER_COLUMNS}, ensure_ascii=False, sort_keys=True) + "\n")
    return len(rows)


def import_ledger(conn: sqlite3.Connection, path: Path | str = LEDGER_PATH) -> int:
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
            conn.execute(
                """INSERT INTO backfill_ledger (url, since, every_days, source, captures, done_at) VALUES (?,?,?,?,?,?)
                   ON CONFLICT(url, since, every_days) DO UPDATE SET done_at=MAX(backfill_ledger.done_at, excluded.done_at),
                     captures=excluded.captures, source=excluded.source""",
                (d["url"], d["since"], int(d["every_days"]), d.get("source"), d.get("captures"), d["done_at"]),
            )
            n += 1
    conn.commit()
    return n


def export_resolutions(conn: sqlite3.Connection, path: Path | str = RESOLUTIONS_PATH) -> int:
    """The trim-map rows the pipeline made itself (the seed's are re-imported each
    run): how every broker row resolved, with the evidence."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = conn.execute(
        f"SELECT {', '.join(RES_COLUMNS)} FROM trim_map WHERE status IN ('auto', 'unmapped', 'conflict') ORDER BY source, source_key"
    ).fetchall()
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            d = {k: r[k] for k in RES_COLUMNS}
            d["evidence"] = json.loads(d["evidence"]) if d.get("evidence") else None
            f.write(json.dumps(d, ensure_ascii=False, sort_keys=True) + "\n")
    return len(rows)


def import_resolutions(conn: sqlite3.Connection, path: Path | str = RESOLUTIONS_PATH) -> int:
    """Upsert the file's rows (a seed 'mapped' row always wins; a seed 'ignored'
    row gives way, as it does live, since the derivative now has a generated car)
    and write each row's brackets back onto its generated car, as the live run did."""
    from pipeline.services import resolve

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
                continue
            ev = d.get("evidence")
            conn.execute(
                """INSERT INTO trim_map (source, source_key, car_id, status, label, example_url, method, evidence, name_key,
                     first_seen_at, last_seen_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(source, source_key) DO UPDATE SET
                     car_id=CASE WHEN trim_map.status='mapped' THEN trim_map.car_id ELSE excluded.car_id END,
                     status=CASE WHEN trim_map.status='mapped' THEN trim_map.status ELSE excluded.status END,
                     label=COALESCE(trim_map.label, excluded.label), example_url=COALESCE(trim_map.example_url, excluded.example_url),
                     method=CASE WHEN trim_map.status='mapped' THEN trim_map.method ELSE excluded.method END,
                     evidence=CASE WHEN trim_map.status='mapped' THEN trim_map.evidence ELSE excluded.evidence END,
                     name_key=COALESCE(excluded.name_key, trim_map.name_key),
                     first_seen_at=MIN(trim_map.first_seen_at, excluded.first_seen_at),
                     last_seen_at=MAX(trim_map.last_seen_at, excluded.last_seen_at)""",
                (d["source"], d["source_key"], car_id, d["status"], d.get("label"), d.get("example_url"), d.get("method"),
                 json.dumps(ev, ensure_ascii=False, sort_keys=True) if ev else None, d.get("name_key"),
                 d["first_seen_at"], d["last_seen_at"]),
            )
            if car_id and ev and ev.get("brackets"):
                gold._apply_bracket_facts(conn, car_id, ev["brackets"], d["last_seen_at"])
            n += 1
    conn.commit()
    return n


def export_used(conn: sqlite3.Connection, path: Path | str = USED_PATH) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = conn.execute(f"SELECT {', '.join(USED_COLUMNS)} FROM used_listings ORDER BY listing_key").fetchall()
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            d = {k: r[k] for k in USED_COLUMNS}
            d["payload"] = json.loads(d["payload"])
            f.write(json.dumps(d, ensure_ascii=False, sort_keys=True) + "\n")
    return len(rows)


def import_used(conn: sqlite3.Connection, path: Path | str = USED_PATH) -> int:
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
                """INSERT INTO used_listings (listing_key, source, make, make_slug, model, model_slug, car_id, price_gbp, year, mileage,
                     present, payload, first_seen_at, last_seen_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(listing_key) DO UPDATE SET
                     price_gbp=CASE WHEN excluded.last_seen_at >= used_listings.last_seen_at THEN excluded.price_gbp ELSE used_listings.price_gbp END,
                     present=CASE WHEN excluded.last_seen_at >= used_listings.last_seen_at THEN excluded.present ELSE used_listings.present END,
                     payload=CASE WHEN excluded.last_seen_at >= used_listings.last_seen_at THEN excluded.payload ELSE used_listings.payload END,
                     car_id=COALESCE(excluded.car_id, used_listings.car_id),
                     first_seen_at=MIN(used_listings.first_seen_at, excluded.first_seen_at),
                     last_seen_at=MAX(used_listings.last_seen_at, excluded.last_seen_at)""",
                (d["listing_key"], d["source"], d.get("make"), d.get("make_slug"), d.get("model"), d.get("model_slug"), car_id,
                 d.get("price_gbp"), d.get("year"), d.get("mileage"), int(d.get("present", 1)),
                 json.dumps(d["payload"], ensure_ascii=False, sort_keys=True), d["first_seen_at"], d["last_seen_at"]),
            )
            n += 1
    conn.commit()
    return n


def export_derivatives(conn: sqlite3.Connection, path: Path | str = DERIVATIVES_PATH) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = conn.execute(f"SELECT {', '.join(DERIVATIVE_COLUMNS)} FROM derivatives ORDER BY make_slug, model_slug, cap_id").fetchall()
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            d = {k: r[k] for k in DERIVATIVE_COLUMNS}
            d["payload"] = json.loads(d["payload"])
            f.write(json.dumps(d, ensure_ascii=False, sort_keys=True) + "\n")
    return len(rows)


def import_derivatives(conn: sqlite3.Connection, path: Path | str = DERIVATIVES_PATH) -> int:
    """Replay the registry; a derivative with no car gets its stub back."""
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
            gold.upsert_derivative(conn, d["payload"], "carwow_model", None, None, d["last_seen_at"], d["first_seen_at"], d["last_seen_at"])
            n += 1
    conn.commit()
    return n


def export_options(conn: sqlite3.Connection, path: Path | str = OPTIONS_PATH) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = conn.execute("SELECT cap_id, payload, first_seen_at, last_seen_at FROM options ORDER BY cap_id").fetchall()
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps({"cap_id": r["cap_id"], "payload": json.loads(r["payload"]), "first_seen_at": r["first_seen_at"],
                                "last_seen_at": r["last_seen_at"]}, ensure_ascii=False, sort_keys=True) + "\n")
    return len(rows)


def import_options(conn: sqlite3.Connection, path: Path | str = OPTIONS_PATH) -> int:
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
            gold.upsert_options(conn, d["payload"], None, None, d["last_seen_at"], d["first_seen_at"], d["last_seen_at"])
            n += 1
    conn.commit()
    return n


def export_used_observations(conn: sqlite3.Connection, path: Path | str = USED_OBS_PATH) -> int:
    """Used asking prices as spans (see schema.sql used_observations)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = conn.execute(f"SELECT {', '.join(USED_OBS_COLUMNS)} FROM used_observations ORDER BY listing_key, observed_at, id").fetchall()
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps({k: r[k] for k in USED_OBS_COLUMNS}, ensure_ascii=False, sort_keys=True) + "\n")
    return len(rows)


def import_used_observations(conn: sqlite3.Connection, path: Path | str = USED_OBS_PATH) -> int:
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
            if not conn.execute("SELECT 1 FROM used_listings WHERE listing_key=?", (d["listing_key"],)).fetchone():
                continue
            conn.execute(
                """INSERT INTO used_observations (listing_key, source, price_gbp, mileage, observed_at, confirmed_at, present)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(listing_key, observed_at, source) DO UPDATE SET
                     confirmed_at=MAX(COALESCE(used_observations.confirmed_at, ''), COALESCE(excluded.confirmed_at, '')),
                     price_gbp=excluded.price_gbp, mileage=excluded.mileage, present=excluded.present""",
                (d["listing_key"], d["source"], d.get("price_gbp"), d.get("mileage"), d["observed_at"], d.get("confirmed_at"), int(d.get("present", 1))),
            )
            n += 1
    conn.commit()
    return n
