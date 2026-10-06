"""Run one provider capability: discover → fetch → Bronze → parse → Silver → Gold."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone

from pipeline import gold
from pipeline.providers.types import Capability, Context, Fetched, Provider, Target


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class RunResult:
    run_id: int
    source: str
    capability: str
    artifacts: int
    new_artifacts: int
    records: int
    gold_rows: int
    unmapped: int
    errors: int = 0
    skipped: int = 0   # optional targets the source does not have (404)


def store_artifact(conn: sqlite3.Connection, source: str, cap: Capability, target: Target,
                   fetched: Fetched, now: str) -> tuple[int, bool]:
    """Content-addressed put. Returns (artifact_id, is_new). A new body for the
    same (source, capability, target) supersedes the previous latest one."""
    sha = hashlib.sha256(fetched.body).hexdigest()
    row = conn.execute(
        "SELECT id FROM artifacts WHERE source=? AND capability=? AND target=? AND sha256=?",
        (source, cap.name, target.identifier, sha),
    ).fetchone()
    if row:
        return int(row["id"]), False
    prev = conn.execute(
        """SELECT id FROM artifacts WHERE source=? AND capability=? AND target=?
             AND superseded_by IS NULL ORDER BY fetched_at DESC, id DESC LIMIT 1""",
        (source, cap.name, target.identifier),
    ).fetchone()
    cur = conn.execute(
        """INSERT INTO artifacts (source, capability, target, url, sha256, content_type, status_code, body,
             fetched_at, parser_version) VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (source, cap.name, target.identifier, fetched.url, sha, fetched.content_type, fetched.status_code,
         fetched.body, now, cap.parser_version),
    )
    new_id = int(cur.lastrowid)
    if prev:
        conn.execute("UPDATE artifacts SET superseded_by=? WHERE id=?", (new_id, prev["id"]))
    return new_id, True


def run(conn: sqlite3.Connection, provider: Provider, capability: str | None = None,
        target: str = "all", ctx: Context | None = None) -> RunResult:
    cap = provider.capability_for(capability)
    if ctx is None:
        from pipeline.db import ROOT
        ctx = Context(root=ROOT)
    # discover may read the catalogue (gold) to know what to fetch.
    ctx.extras.setdefault("db", conn)
    started = _now()
    cur = conn.execute(
        "INSERT INTO runs (source, capability, target, started_at, status) VALUES (?,?,?,?,'running')",
        (provider.name, cap.name, target, started),
    )
    run_id = int(cur.lastrowid)
    conn.commit()

    n_art = n_new = n_rec = n_unmapped = n_skipped = 0
    records: dict[str, list] = {}
    failures: list[str] = []
    try:
        for i, t in enumerate(cap.discover(Target(identifier=target), ctx)):
            if ctx.max_targets is not None and i >= ctx.max_targets:
                break
            # One bad target (site down, layout changed) must not sink the run.
            try:
                fetched = cap.fetch(t, ctx)
                if fetched.status_code != 200:
                    raise RuntimeError(f"HTTP {fetched.status_code}")
                parsed = list(cap.parse(fetched.body, t))
            except Exception as e:  # noqa: BLE001
                # A target the provider guessed at (a broker page for a model it
                # may not list) is allowed not to exist.
                if t.metadata.get("optional") and "404" in str(e):
                    n_skipped += 1
                    continue
                failures.append(f"{t.identifier}: {e}")
                continue
            now = _now()
            art_id, is_new = store_artifact(conn, provider.name, cap, t, fetched, now)
            n_art += 1
            n_new += int(is_new)
            # Re-parsing an existing artifact replaces its Silver rows (idempotent).
            conn.execute("DELETE FROM source_rows WHERE artifact_id=?", (art_id,))
            for rec in parsed:
                conn.execute(
                    "INSERT INTO source_rows (artifact_id, source, kind, source_key, row, parsed_at) VALUES (?,?,?,?,?,?)",
                    (art_id, provider.name, rec.kind, rec.key, json.dumps(rec.row, ensure_ascii=False, sort_keys=True), now),
                )
                n_rec += 1
                if rec.kind == "offer" and not rec.row.get("car_id"):
                    ref = dict(rec.row.get("car_ref") or {}, provider=provider.name)
                    car_id, status = gold.resolve_car(conn, ref.get("source", provider.name), ref.get("key", ""),
                                                      ref.get("label"), fetched.url, now, ref=ref)
                    if car_id is None:
                        n_unmapped += int(status == "unmapped")
                        continue
                    rec.row["car_id"] = car_id
                elif rec.kind == "spec" and not rec.row.get("car_id"):
                    # Specs for every variant are kept; a miss is not a mapping task.
                    ref = rec.row.get("car_ref") or {}
                    car_id, _ = gold.resolve_car(conn, ref.get("source", provider.name), ref.get("key", ""),
                                                 ref.get("label"), fetched.url, now, record_miss=False)
                    rec.row["car_id"] = car_id
                records.setdefault(rec.kind, []).append((art_id, rec))
        n_gold = gold.write(conn, provider.name, cap.kinds, records, run_id)
        status = "ok" if (n_art or not failures) else "error"
        conn.execute(
            "UPDATE runs SET finished_at=?, status=?, artifacts=?, records=?, unmapped=?, errors=?, error=? WHERE id=?",
            (_now(), status, n_art, n_rec, n_unmapped, len(failures), "\n".join(failures) or None, run_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        conn.execute(
            "UPDATE runs SET finished_at=?, status='error', artifacts=?, records=?, unmapped=?, error=? WHERE id=?",
            (_now(), n_art, n_rec, n_unmapped, traceback.format_exc(), run_id),
        )
        conn.commit()
        raise
    return RunResult(run_id, provider.name, cap.name, n_art, n_new, n_rec, n_gold, n_unmapped, len(failures), n_skipped)
