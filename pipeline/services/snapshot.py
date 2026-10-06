"""Static snapshot exporter: Gold → a directory of JSON the SPA reads.

Layout (schema_version 2):
    manifest.json       {schema_version, generated_at, counts, runs}
    cars.json           [car + requirement_check + deal_summary]
    offers.json         [latest observation of each offer + metrics + freshness]
    requirements.json   the requirements document as-is
    data.json           providers, recent runs, unmapped trims, offer states

An offer's current values are its latest observation. Freshness is derived here
from the observation history, never typed by hand:
    state   gone (latest check did not find it) | expired (valid_to passed or the
            source said so) | otherwise the observed status (live, lead, ...)
    stale   an active offer whose last sighting is older than STALE_DAYS
Finance maths is computed here, once, so the browser never needs its own copy.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from model.deal_math import compute

# Bump on any incompatible shape change; the SPA warns loudly on skew.
SCHEMA_VERSION = "2"

# Observed statuses that count as "an offer you could act on today".
ACTIVE_STATUSES = {"live", "lead", "derived", "illustrative"}
STALE_DAYS = 14
HISTORY_FIELDS = ("monthly_payment", "vehicle_price", "apr", "gfv", "initial_rental", "monthly_rental")


def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


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


def _is_current(o: dict) -> bool:
    f = o["freshness"]
    return f["state"] in ACTIVE_STATUSES and not f["stale"]


def deal_summary(offers: list[dict], metrics_by_id: dict[str, dict]) -> dict:
    current = [o for o in offers if _is_current(o)]
    cash = [o for o in current if o["finance_type"] == "cash" and o.get("vehicle_price")]
    best_cash = min(cash, key=lambda o: o["vehicle_price"]) if cash else None

    pcps = []
    for o in current:
        m = metrics_by_id.get(o["id"])
        if o["finance_type"] == "pcp" and m and "skipped" not in m and (o.get("customer_deposit") or 0) == 0:
            pcps.append((o, m))
    best_pcp = min(pcps, key=lambda om: om[1]["monthly_payment"]) if pcps else None

    pchs = [(o, metrics_by_id[o["id"]]) for o in current
            if o["finance_type"] == "pch" and o["id"] in metrics_by_id and "skipped" not in metrics_by_id[o["id"]]]
    best_pch = min(pchs, key=lambda om: om[1]["effective_monthly"]) if pchs else None

    def age(o):
        return o["freshness"]["age_days"] if o else None

    return {
        "offers": len(offers),
        "current_offers": len(current),
        "best_cash_price": best_cash["vehicle_price"] if best_cash else None,
        "best_cash_offer_id": best_cash["id"] if best_cash else None,
        "best_cash_age_days": age(best_cash),
        "best_pcp_monthly": best_pcp[1]["monthly_payment"] if best_pcp else None,
        "best_pcp_offer_id": best_pcp[0]["id"] if best_pcp else None,
        "best_pcp_age_days": age(best_pcp[0]) if best_pcp else None,
        "best_pch_effective_monthly": best_pch[1]["effective_monthly"] if best_pch else None,
        "best_pch_offer_id": best_pch[0]["id"] if best_pch else None,
        "best_pch_age_days": age(best_pch[0]) if best_pch else None,
    }


def load_cars(conn: sqlite3.Connection) -> list[dict]:
    return [json.loads(r["payload"]) for r in conn.execute("SELECT payload FROM cars ORDER BY id")]


def load_requirements(conn: sqlite3.Connection) -> dict:
    row = conn.execute("SELECT payload FROM requirements WHERE id = 1").fetchone()
    return json.loads(row["payload"]) if row else {}


def _freshness(obs: list[sqlite3.Row], payload: dict, today: date) -> dict:
    latest = obs[-1]
    seen = [o for o in obs if o["present"]]
    last_seen = seen[-1]["observed_at"] if seen else None
    age = (today - date.fromisoformat(last_seen[:10])).days if last_seen else None
    if not latest["present"]:
        state = "gone"
    elif payload.get("valid_to") and payload["valid_to"] < today.isoformat():
        state = "expired"
    else:
        state = latest["status"]
    stale = state in ACTIVE_STATUSES and age is not None and age > STALE_DAYS
    history = []
    for o in obs:
        p = json.loads(o["payload"])
        history.append({"observed_at": o["observed_at"], "present": bool(o["present"]), "source": o["source"],
                        **{k: p.get(k) for k in HISTORY_FIELDS if p.get(k) is not None}})
    return {
        "state": state,
        "stale": stale,
        "age_days": age,
        "first_seen_at": obs[0]["observed_at"],
        "last_seen_at": last_seen,
        "last_checked_at": latest["observed_at"],
        "observations": len(obs),
        "present": bool(latest["present"]),
        "history": history,
    }


def latest_offers(conn: sqlite3.Connection, today: date | None = None) -> list[dict]:
    """One dict per offer key: the latest observation's payload (id = offer key)
    plus a `freshness` block derived from the whole history."""
    today = today or datetime.now(timezone.utc).date()
    rows = conn.execute(
        "SELECT * FROM offer_observations ORDER BY offer_key, observed_at, id"
    ).fetchall()
    groups: dict[str, list[sqlite3.Row]] = {}
    for r in rows:
        groups.setdefault(r["offer_key"], []).append(r)
    out = []
    for key, obs in groups.items():
        payload = json.loads(obs[-1]["payload"])
        payload["id"] = key
        payload["car_id"] = obs[-1]["car_id"]
        payload["provider"] = obs[-1]["source"]
        payload["freshness"] = _freshness(obs, payload, today)
        out.append(payload)
    out.sort(key=lambda o: (o["freshness"]["last_checked_at"], o["id"]))
    return out


def latest_runs(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    rows = conn.execute(
        "SELECT id, source, capability, target, started_at, finished_at, status, artifacts, records, unmapped "
        "FROM runs ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


def unmapped_trims(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT source, source_key, label, example_url, first_seen_at, last_seen_at FROM trim_map "
        "WHERE status='unmapped' ORDER BY source, source_key"
    ).fetchall()
    return [dict(r) for r in rows]


def export_snapshot(conn: sqlite3.Connection, out_dir: Path | str, generated_at: str | None = None) -> dict:
    from pipeline.providers import PROVIDERS

    out = Path(out_dir)
    generated_at = generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    today = date.fromisoformat(generated_at[:10])

    cars = load_cars(conn)
    offers = latest_offers(conn, today)
    requirements = load_requirements(conn)

    metrics = {m["id"]: m for m in compute(offers)}
    for o in offers:
        m = dict(metrics.get(o["id"], {}))
        for k in ("id", "car_id", "finance_type", "status"):
            m.pop(k, None)
        o["metrics"] = m

    by_car: dict[str, list[dict]] = {}
    for o in offers:
        by_car.setdefault(o["car_id"], []).append(o)
    for c in cars:
        c["requirement_check"] = evaluate_hard(requirements, c)
        c["deal_summary"] = deal_summary(by_car.get(c["id"], []), metrics)

    states: dict[str, int] = {}
    for o in offers:
        s = o["freshness"]["state"] + (" (stale)" if o["freshness"]["stale"] else "")
        states[s] = states.get(s, 0) + 1
    n_obs = conn.execute("SELECT COUNT(*) FROM offer_observations").fetchone()[0]
    unmapped = unmapped_trims(conn)
    data_page = {
        "generated_at": generated_at,
        "stale_days": STALE_DAYS,
        "providers": [
            {"name": p.name, "capabilities": [{"name": c.name, "kinds": list(c.kinds), "parser_version": c.parser_version}
                                              for c in p.capabilities.values()]}
            for p in PROVIDERS.values()
        ],
        "runs": latest_runs(conn),
        "unmapped_trims": unmapped,
        "offer_states": states,
        "counts": {"cars": len(cars), "offers": len(offers), "observations": n_obs,
                   "trim_map_mapped": conn.execute("SELECT COUNT(*) FROM trim_map WHERE status='mapped'").fetchone()[0],
                   "trim_map_unmapped": len(unmapped)},
    }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "counts": {
            "cars": len(cars),
            "offers": len(offers),
            "observations": n_obs,
            "cash_benchmarks": sum(1 for o in offers if o["finance_type"] == "cash"),
            "unmapped_trims": len(unmapped),
        },
        "runs": latest_runs(conn, 10),
    }
    _write(out / "cars.json", cars)
    _write(out / "offers.json", offers)
    _write(out / "requirements.json", requirements)
    _write(out / "data.json", data_page)
    _write(out / "manifest.json", manifest)
    legacy = out / "deals.json"
    if legacy.exists():
        legacy.unlink()
    return manifest
