"""Backfill from the Wayback Machine: archived copies of the pages the live
providers read, parsed with the same parsers, dated by the archive timestamp.

A live provider gains a 'backfill' capability from `backfill_capability(base)`:
discover asks the CDX index for every 200 capture of each of the base
capability's URLs since a date, thins them to one per week (and drops captures
whose body digest matches the one kept before), and yields a target per capture
(`ctx.extras["shard"] = (i, n)` keeps every n-th page only, so a big provider
splits across jobs; `ctx.extras["budget_seconds"]` stops taking on new pages
after that long; a page whose captures were all consumed is recorded in the
`backfill_ledger` table and skipped by later runs, so a run that stops at its
budget resumes where it left off);
fetch pulls the raw page (`/web/<ts>id_/<url>`, no toolbar); parse is the base
parser, which reads `observed_at` and `original_url` off the target. Gold then
folds each dated sighting into the offer's span history (`gold._merge_sighting`).
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from collections.abc import Iterator
from datetime import datetime, timezone
from urllib.parse import urlencode

from pipeline.providers.http import FetchError, fetch_url
from pipeline.providers.types import Capability, Context, Fetched, Target

CDX = "https://web.archive.org/cdx/search/cdx"
DEFAULT_SINCE = "2025-01-01"
DEFAULT_EVERY_DAYS = 7


def ts_to_iso(ts: str) -> str:
    return datetime.strptime(ts[:14], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc).isoformat(timespec="seconds")


def archive_url(ts: str, url: str) -> str:
    return f"https://web.archive.org/web/{ts}id_/{url}"


def cdx_snapshots(url: str, since: str, ctx: Context) -> list[tuple[str, str]]:
    """[(timestamp, digest)] of every 200 capture of `url` since `since` (YYYY-MM-DD), one per day."""
    q = urlencode({
        "url": url, "output": "json", "from": since.replace("-", ""), "fl": "timestamp,statuscode,digest",
        "filter": "statuscode:200", "collapse": "timestamp:8",
    })
    # One retry: the index answers 503 / 'connection refused' in bursts and usually
    # recovers within seconds, while a truly hung query costs two timeouts, not three.
    # A page whose index still fails is skipped this run (re-run the backfill later).
    f = fetch_url(f"{CDX}?{q}", ctx, accept="application/json", timeout=45, retries=1)
    rows = json.loads(f.body or b"[]")
    return [(r[0], r[2]) for r in rows[1:]]


def thin(snaps: list[tuple[str, str]], every_days: int) -> list[tuple[str, str]]:
    """At most one capture per `every_days` window, skipping bodies identical to the last kept one."""
    out: list[tuple[str, str]] = []
    last_day = None
    last_digest = None
    for ts, digest in sorted(snaps):
        day = datetime.strptime(ts[:8], "%Y%m%d").toordinal()
        if last_day is not None and day - last_day < every_days:
            continue
        if digest == last_digest:
            continue
        out.append((ts, digest))
        last_day, last_digest = day, digest
    return out


def ledger_done(conn: sqlite3.Connection | None, url: str, since: str, every: int) -> bool:
    if conn is None:
        return False
    try:
        return conn.execute("SELECT 1 FROM backfill_ledger WHERE url=? AND since=? AND every_days=?",
                            (url, since, every)).fetchone() is not None
    except sqlite3.OperationalError:
        return False


def ledger_mark(conn: sqlite3.Connection | None, url: str, since: str, every: int, source: str, captures: int,
                store=None) -> None:
    """A page whose captures are all folded in. Kept in the raw store's log (the build reads it back), and in
    the database this run discovers from."""
    entry = {"url": url, "since": since, "every_days": every, "source": source, "captures": captures,
             "done_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if store is not None:
        store.log("backfill", entry)
    if conn is None:
        return
    conn.execute(
        """INSERT INTO backfill_ledger (url, since, every_days, source, captures, done_at) VALUES (?,?,?,?,?,?)
           ON CONFLICT(url, since, every_days) DO UPDATE SET source=excluded.source, captures=excluded.captures, done_at=excluded.done_at""",
        (url, since, every, source, captures, entry["done_at"]),
    )


def backfill_capability(base: Capability, *, since: str = DEFAULT_SINCE, every_days: int = DEFAULT_EVERY_DAYS) -> Capability:
    def discover(target: Target, ctx: Context) -> Iterator[Target]:
        since_ = str(ctx.extras.get("since") or since)
        every = int(ctx.extras.get("every_days") or every_days)
        shard, shards = ctx.extras.get("shard") or (0, 1)
        budget = ctx.extras.get("budget_seconds")
        conn = ctx.extras.get("db")
        started = time.monotonic()
        ident, _, only_ts = target.identifier.partition("@")
        pending: tuple[str, int] | None = None   # the page whose captures the runner is consuming

        def settle() -> None:
            # The runner pulls targets lazily, so by the time discover moves on
            # to the next page every capture of the previous one has been
            # fetched and parsed (or failed): that page is done.
            if pending is not None:
                ledger_mark(conn, pending[0], since_, every, base.name, pending[1], ctx.extras.get("raw_store"))

        for i, t in enumerate(base.discover(Target(ident), ctx)):
            if i % shards != shard:
                continue  # another job of the chunked backfill takes this page
            url = t.metadata["url"]
            if not only_ts and ledger_done(conn, url, since_, every):
                continue  # folded in by an earlier run (data/history/backfill.jsonl)
            settle()
            if budget is not None and pending is not None and time.monotonic() - started > float(budget):
                # At least one page per run, so a slow archive still makes progress.
                print(f"  time budget of {budget}s spent; stopping at {t.identifier} (the ledger resumes here next run)",
                      file=sys.stderr, flush=True)
                return
            pending = None
            try:
                snaps = thin(cdx_snapshots(url, since_, ctx), every)
            except (FetchError, ValueError) as e:
                print(f"  wayback index for {url}: {e}", file=sys.stderr, flush=True)
                continue
            print(f"  {t.identifier}: {len(snaps)} captures to fold in", file=sys.stderr, flush=True)
            pending = (url, len(snaps))
            for ts, digest in snaps:
                if only_ts and ts != only_ts:
                    continue
                yield Target(identifier=f"{t.identifier}@{ts}", metadata={
                    **t.metadata, "url": archive_url(ts, url), "original_url": url,
                    "observed_at": ts_to_iso(ts), "wayback_ts": ts, "wayback_digest": digest,
                })
        settle()

    def fetch(target: Target, ctx: Context) -> Fetched:
        return fetch_url(target.metadata["url"], ctx, timeout=60, retries=1)

    return Capability(name="backfill", parser_version=base.parser_version, discover=discover, fetch=fetch,
                      parse=base.parse, kinds=base.kinds)


def observed_at_for(target: Target) -> str:
    """The archive timestamp for a backfilled target, else now."""
    return target.metadata.get("observed_at") or datetime.now(timezone.utc).isoformat(timespec="seconds")


def original_url(target: Target) -> str:
    return target.metadata.get("original_url") or target.metadata["url"]
