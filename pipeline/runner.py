"""Scrape one provider capability into the raw store: discover -> fetch -> keep.

Every response is kept exactly as it came (pipeline/raw.py), a failed one too when the
site answered. The page is parsed straight away only to count its records and to let
the providers that run later tonight discover from what this one found (the catalogue
before the model pages, the registry before the configurator): those records go into
the disposable build database, which the build afterwards replaces from scratch.
"""
from __future__ import annotations

import sqlite3
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone

from pipeline import gold
from pipeline.providers.http import FetchError
from pipeline.providers.types import Capability, Context, Provider, Target
from pipeline.raw import RawStore, sha256


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class RunResult:
    source: str
    capability: str
    fetches: int
    new_bodies: int
    records: int
    errors: int = 0
    skipped: int = 0   # optional targets the source does not have (404)


def _keep(store: RawStore, provider: Provider, cap: Capability, t: Target, url: str | None, status: int | None,
          body: bytes | None, content_type: str | None, error: str | None, fetched_at: str) -> bool:
    """Keep one response; True when its body was new to the store."""
    new = body is not None and not store.has(sha256(body))
    meta = {k: v for k, v in t.metadata.items() if k != "observed_at"} or None
    if t.metadata.get("observed_at"):   # a Wayback capture: the parser dates it by the archive
        meta = dict(meta or {}, observed_at=t.metadata["observed_at"])
    origin = "wayback" if cap.name == "backfill" else "live"
    store.save(source=provider.name, capability=cap.name, target=t.identifier, metadata=meta, url=url,
               fetched_at=fetched_at, status=status, body=body, content_type=content_type, error=error, origin=origin)
    return new


def _keep_parts(store: RawStore, provider: Provider, cap: Capability, t: Target, parts: tuple, fetched_at: str) -> None:
    """Each response a combined fetch was made of, byte for byte."""
    for i, p in enumerate(parts):
        store.save(source=provider.name, capability=cap.name, target=t.identifier,
                   metadata={"part": i + 1, "of": len(parts)}, url=p.url, fetched_at=fetched_at, status=p.status_code,
                   body=p.body, content_type=p.content_type, origin="wayback" if cap.name == "backfill" else "live", role="part")


def run(store: RawStore, conn: sqlite3.Connection | None, provider: Provider, capability: str | None = None,
        target: str = "all", ctx: Context | None = None) -> RunResult:
    cap = provider.capability_for(capability)
    if ctx is None:
        from pipeline.db import ROOT
        ctx = Context(root=ROOT)
    if conn is not None:
        ctx.extras.setdefault("db", conn)   # discover may read the catalogue to know what to fetch
    started = _now()
    n_fetch = n_new = n_rec = n_skipped = 0
    failures: list[str] = []
    status = "ok"
    try:
        for i, t in enumerate(cap.discover(Target(identifier=target), ctx)):
            if ctx.max_targets is not None and i >= ctx.max_targets:
                break
            fetched_at = _now()
            try:
                fetched = cap.fetch(t, ctx)
            except FetchError as e:
                if e.status is not None or e.body is not None:
                    _keep(store, provider, cap, t, e.url or t.metadata.get("url"), e.status, e.body, None, str(e), fetched_at)
                else:
                    _keep(store, provider, cap, t, e.url or t.metadata.get("url"), None, None, None, str(e), fetched_at)
                n_fetch += 1
                # A target the provider guessed at (a broker page for a model it may not list) is allowed not to exist.
                if t.metadata.get("optional") and e.status == 404:
                    n_skipped += 1
                    continue
                failures.append(f"{t.identifier}: {e}")
                continue
            except Exception as e:  # noqa: BLE001
                _keep(store, provider, cap, t, t.metadata.get("url"), None, None, None, repr(e), fetched_at)
                n_fetch += 1
                failures.append(f"{t.identifier}: {e}")
                continue
            n_fetch += 1
            _keep_parts(store, provider, cap, t, fetched.parts, fetched_at)
            n_new += int(_keep(store, provider, cap, t, fetched.url, fetched.status_code, fetched.body, fetched.content_type,
                               None if fetched.status_code == 200 else f"HTTP {fetched.status_code}", fetched_at))
            if fetched.status_code != 200:
                failures.append(f"{t.identifier}: HTTP {fetched.status_code}")
                continue
            # One bad page (a layout change) must not sink the run; the body is kept either way.
            try:
                meta = dict(t.metadata)
                meta.setdefault("observed_at", fetched_at)
                records = list(cap.parse(fetched.body, Target(identifier=t.identifier, metadata=meta)))
            except Exception as e:  # noqa: BLE001
                failures.append(f"{t.identifier}: parse: {e}")
                continue
            n_rec += len(records)
            if conn is not None:
                by_kind: dict[str, list] = {}
                for r in records:
                    if r.kind not in ("offer", "car", "trim_map"):
                        by_kind.setdefault(r.kind, []).append((None, r))
                gold.write(conn, provider.name, by_kind, None, now=meta["observed_at"])
                conn.commit()
        status = "ok" if (n_fetch - len(failures) > 0 or not failures) else "error"
        return RunResult(provider.name, cap.name, n_fetch, n_new, n_rec, len(failures), n_skipped)
    except Exception:
        status = "error"
        failures.append(traceback.format_exc())
        raise
    finally:
        store.log_run({"source": provider.name, "capability": cap.name, "target": target, "started_at": started,
                       "finished_at": _now(), "status": status, "fetches": n_fetch, "new_bodies": n_new, "records": n_rec,
                       "errors": len(failures), "skipped": n_skipped, "error": "\n".join(failures)[:20000] or None})
