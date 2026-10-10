"""The committed history as a legacy source: the only copy of what was fetched
before the raw store existed.

Until 10 Oct 2026 the pipeline threw its fetched pages away and committed
`data/history/*.jsonl` instead: already-parsed records, each pinned to the car it
had been matched to. `migrate` copies every committed version of every one of those
files into the raw store, byte for byte, as fetches of source `legacy` dated by
their commit. It is idempotent, so re-running it after more commits (the GitHub
nightly keeps committing until the laptop takes over) adds only the new versions.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from pipeline.db import ROOT
from pipeline.raw import RawStore, fetch_id, sha256

HISTORY_DIR = "data/history"
SOURCE = "legacy"
# The order a commit's files are applied in: a used listing before its price spans.
ORDER = ("models", "derivatives", "specs", "options", "configurations", "used", "used_observations", "backfill",
         "observations", "resolutions")
# The owner's own entries are read from data/seed and data/pastes in git, not from their copies here.
OWNER_PROVIDERS = ("manual_seed", "carwow_paste")


def _git(repo: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True).stdout


def history_versions(repo: Path = ROOT) -> list[dict]:
    """Every (commit, path) where a history file was added or changed, oldest first,
    across every ref the clone has."""
    out = _git(repo, "log", "--all", "--reverse", "--date-order", "--no-renames", "--format=@%H%x09%cI%x09%s",
               "--name-status", "--", HISTORY_DIR).decode("utf-8")
    versions: list[dict] = []
    commit = None
    for line in out.splitlines():
        if not line.strip():
            continue
        if line.startswith("@"):
            sha, when, subject = line[1:].split("\t", 2)
            commit = {"commit": sha, "committed_at": when, "subject": subject}
            continue
        status, path = line.split("\t", 1)
        if status[0] in "AM" and path.endswith(".jsonl") and commit:
            versions.append({**commit, "path": path})
    return versions


def _utc(iso: str) -> str:
    return datetime.fromisoformat(iso).astimezone(timezone.utc).isoformat(timespec="seconds")


def migrate(store: RawStore, repo: Path = ROOT) -> dict:
    """Copy every committed version of data/history/*.jsonl into the raw store."""
    have = store.ids()
    added = skipped = 0
    for v in history_versions(repo):
        body = _git(repo, "cat-file", "blob", f"{v['commit']}:{v['path']}")
        name = Path(v["path"]).name
        entry = {
            "origin": SOURCE, "source": SOURCE, "capability": Path(name).stem, "target": name,
            "url": f"git:{v['commit']}:{v['path']}", "fetched_at": _utc(v["committed_at"]),
        }
        entry["sha256"] = sha256(body)
        if fetch_id(entry) in have:
            skipped += 1
            continue
        store.save(source=SOURCE, capability=entry["capability"], target=name,
                   metadata={"commit": v["commit"], "path": v["path"], "subject": v["subject"]},
                   url=entry["url"], fetched_at=entry["fetched_at"], status=200, body=body,
                   content_type="application/x-ndjson", origin=SOURCE)
        added += 1
    return {"added": added, "already_there": skipped}


def read(capability: str, body: bytes) -> list[dict]:
    """A legacy history file as rows of what each source said and when, with the
    matching taken out: no row keeps the car it was pinned to, and the record of the
    pipeline's own matches (resolutions.jsonl) yields nothing at all."""
    if capability == "resolutions":
        return []
    rows = []
    for line in body.decode("utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        d.pop("car_id", None)
        if isinstance(d.get("payload"), dict):
            d["payload"].pop("car_id", None)
        if capability == "observations":
            if d.get("source") in OWNER_PROVIDERS:
                continue
            upgrade(d["source"], d["payload"])
        rows.append(d)
    return rows


def upgrade(provider: str, row: dict) -> None:
    """What today's parser would derive from fields the legacy row kept. A span kept the
    payload of its first sighting, so a field a parser learned to derive later is
    missing from older rows although everything it is derived from is there."""
    ref = row.get("car_ref")
    if provider == "ncd" and isinstance(ref, dict) and ref.get("rrp") is None:
        from pipeline.providers.ncd import OTR_EXTRAS_GBP
        if row.get("vehicle_price") and row.get("saving_stated"):
            ref["rrp"] = round(row["vehicle_price"] + row["saving_stated"] - OTR_EXTRAS_GBP, 2)
