"""Static snapshot exporter: Gold → a directory of JSON the SPA reads.

Layout (schema_version 1):
    manifest.json       {schema_version, generated_at, counts, runs}
    cars.json           [car + requirement_check + deal_summary]
    deals.json          [deal + metrics]            (metrics from model.deal_math)
    requirements.json   the requirements document as-is

Finance maths is computed here, once, so the browser never needs its own copy.
Files are written with sorted keys and indent=1 so git diffs stay readable.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from model.deal_math import compute

# Bump on any incompatible shape change; the SPA warns loudly on skew.
SCHEMA_VERSION = "1"

# Deals that count when summarising "what can I actually get this car for".
ACTIVE_STATUSES = {"live", "lead", "derived", "illustrative"}


def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def evaluate_hard(requirements: dict, car: dict) -> dict:
    """Check a car against the hard rules. Rules with applies_to == 'deal' are
    skipped; a rule whose field the car does not carry is 'unknown', not a fail."""
    failures: list[str] = []
    unknown: list[str] = []
    for rule in requirements.get("hard", []):
        if rule.get("applies_to") == "deal":
            continue
        value = car.get(rule.get("field"))
        if value is None or value == "unknown":
            unknown.append(rule["id"])
            continue
        op, want = rule.get("op"), rule.get("value")
        if op == "==":
            ok = value == want
        elif op == "in":
            ok = value in want
        elif op == ">=":
            ok = value >= want
        elif op == "<=":
            ok = value <= want
        else:
            unknown.append(rule["id"])
            continue
        if not ok:
            failures.append(rule["id"])
    return {"passes": not failures, "failures": failures, "unknown": unknown}


def deal_summary(deals: list[dict], metrics_by_id: dict[str, dict]) -> dict:
    active = [d for d in deals if d.get("status") in ACTIVE_STATUSES]
    cash = [d for d in active if d["finance_type"] == "cash" and d.get("vehicle_price")]
    best_cash = min(cash, key=lambda d: d["vehicle_price"]) if cash else None

    pcps = []
    for d in active:
        m = metrics_by_id.get(d["id"])
        if d["finance_type"] != "pcp" or not m or "skipped" in m:
            continue
        if (d.get("customer_deposit") or 0) == 0:
            pcps.append((d, m))
    best_pcp = min(pcps, key=lambda dm: dm[1]["monthly_payment"]) if pcps else None

    pchs = []
    for d in active:
        m = metrics_by_id.get(d["id"])
        if d["finance_type"] == "pch" and m and "skipped" not in m:
            pchs.append((d, m))
    best_pch = min(pchs, key=lambda dm: dm[1]["effective_monthly"]) if pchs else None

    return {
        "deals": len(deals),
        "active_deals": len(active),
        "best_cash_price": best_cash["vehicle_price"] if best_cash else None,
        "best_cash_deal_id": best_cash["id"] if best_cash else None,
        "best_pcp_monthly": best_pcp[1]["monthly_payment"] if best_pcp else None,
        "best_pcp_deal_id": best_pcp[0]["id"] if best_pcp else None,
        "best_pch_effective_monthly": best_pch[1]["effective_monthly"] if best_pch else None,
        "best_pch_deal_id": best_pch[0]["id"] if best_pch else None,
    }


def load_gold(conn: sqlite3.Connection) -> tuple[list[dict], list[dict], dict]:
    cars = [json.loads(r["payload"]) for r in conn.execute("SELECT payload FROM cars ORDER BY id")]
    deals = [
        json.loads(r["payload"])
        for r in conn.execute("SELECT payload FROM deals ORDER BY captured_at, id")
    ]
    row = conn.execute("SELECT payload FROM requirements WHERE id = 1").fetchone()
    requirements = json.loads(row["payload"]) if row else {}
    return cars, deals, requirements


def latest_runs(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """SELECT source, capability, finished_at, status, artifacts, records
             FROM runs r
            WHERE id = (SELECT MAX(id) FROM runs WHERE source = r.source AND capability = r.capability)
            ORDER BY source, capability"""
    ).fetchall()
    return [dict(r) for r in rows]


def export_snapshot(conn: sqlite3.Connection, out_dir: Path | str, generated_at: str | None = None) -> dict:
    out = Path(out_dir)
    cars, deals, requirements = load_gold(conn)

    metrics = {m["id"]: m for m in compute(deals)}
    for d in deals:
        m = dict(metrics.get(d["id"], {}))
        for k in ("id", "car_id", "finance_type", "status"):
            m.pop(k, None)
        d["metrics"] = m

    by_car: dict[str, list[dict]] = {}
    for d in deals:
        by_car.setdefault(d["car_id"], []).append(d)
    for c in cars:
        c["requirement_check"] = evaluate_hard(requirements, c)
        c["deal_summary"] = deal_summary(by_car.get(c["id"], []), metrics)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "counts": {
            "cars": len(cars),
            "deals": len(deals),
            "cash_benchmarks": sum(1 for d in deals if d["finance_type"] == "cash"),
        },
        "runs": latest_runs(conn),
    }
    _write(out / "cars.json", cars)
    _write(out / "deals.json", deals)
    _write(out / "requirements.json", requirements)
    _write(out / "manifest.json", manifest)
    return manifest
