"""Backfill from the Wayback Machine: archived copies of the pages the live
providers read, parsed with the same parsers, dated by the archive timestamp.

A live provider gains a 'backfill' capability from `backfill_capability(base)`:
discover asks the CDX index for every 200 capture of each of the base
capability's URLs since a date, thins them to one per week (and drops captures
whose body digest matches the one kept before), and yields a target per capture;
fetch pulls the raw page (`/web/<ts>id_/<url>`, no toolbar); parse is the base
parser, which reads `observed_at` and `original_url` off the target. Gold then
folds each dated sighting into the offer's span history (`gold._merge_sighting`).
"""
from __future__ import annotations

import json
import sys
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
    # Fail fast: a hung or 'temporarily offline' index query costs one timeout, not
    # three, and the page is simply skipped this run (re-run the backfill later).
    f = fetch_url(f"{CDX}?{q}", ctx, accept="application/json", timeout=45, retries=0)
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


def backfill_capability(base: Capability, *, since: str = DEFAULT_SINCE, every_days: int = DEFAULT_EVERY_DAYS) -> Capability:
    def discover(target: Target, ctx: Context) -> Iterator[Target]:
        since_ = str(ctx.extras.get("since") or since)
        every = int(ctx.extras.get("every_days") or every_days)
        ident, _, only_ts = target.identifier.partition("@")
        for t in base.discover(Target(ident), ctx):
            url = t.metadata["url"]
            try:
                snaps = thin(cdx_snapshots(url, since_, ctx), every)
            except (FetchError, ValueError) as e:
                print(f"  wayback index for {url}: {e}", file=sys.stderr, flush=True)
                continue
            print(f"  {t.identifier}: {len(snaps)} captures to fold in", file=sys.stderr, flush=True)
            for ts, digest in snaps:
                if only_ts and ts != only_ts:
                    continue
                yield Target(identifier=f"{t.identifier}@{ts}", metadata={
                    **t.metadata, "url": archive_url(ts, url), "original_url": url,
                    "observed_at": ts_to_iso(ts), "wayback_ts": ts, "wayback_digest": digest,
                })

    def fetch(target: Target, ctx: Context) -> Fetched:
        return fetch_url(target.metadata["url"], ctx, timeout=60, retries=1)

    return Capability(name="backfill", parser_version=base.parser_version, discover=discover, fetch=fetch,
                      parse=base.parse, kinds=base.kinds)


def observed_at_for(target: Target) -> str:
    """The archive timestamp for a backfilled target, else now."""
    return target.metadata.get("observed_at") or datetime.now(timezone.utc).isoformat(timespec="seconds")


def original_url(target: Target) -> str:
    return target.metadata.get("original_url") or target.metadata["url"]
