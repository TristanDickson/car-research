"""What each stage of the pipeline did, night by night, and what each level holds, for the Data page.

The stages are scrape (each live source fetches into the raw store), build (every stored page parsed,
matched to cars and folded into the database, then the snapshot written) and publish (the snapshot
committed to `main`, which deploys the site). The levels, per source, are the pages the raw store
holds, the records read from them, the records that name a car, and the rows that reach the snapshot.

Where each comes from:
  scrape   the raw store's run log (`logs/runs-*.jsonl`, written by pipeline/runner.py), with the
           refusals counted from the raw store's index
  build    the raw store's build log (`logs/builds-*.jsonl`), written by `pipeline build` and
           `pipeline nightly` when they write the real snapshot (never by a build into a scratch folder)
  publish  the data commits on the branch (`git log -- web/public/data/manifest.json`)

Nights are labelled as pipeline/providers/politeness.py labels them: the date twelve hours before, so
the 03:17 run and an evening's hand runs before it carry the same label.
"""
from __future__ import annotations

import json
import subprocess
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

NIGHTS_KEPT = 42
REFUSED = (429, 403)
# Sources whose records describe a model, a trim or a variant rather than one car: they are laid over
# the cars by model and battery (services/claims.py), so "names a car" does not apply to them.
DESCRIBES_MODELS = ("carwow_catalog", "carwow_model", "evdb", "evdb_cars", "kia_specs", "hyundai_specs",
                    "hyundai_configurator", "carwow_options", "adac", "whatcar")


def night_of(iso: str | None) -> str | None:
    if not iso:
        return None
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (t.astimezone(timezone.utc) - timedelta(hours=12)).date().isoformat()


def raw_levels(entries: list[dict]) -> dict[str, dict]:
    """Per source, what the raw store holds: fetches (each page a fetch combined counted once), the
    responses kept with them, failures and refusals, distinct bodies, the first and last fetch."""
    from pipeline.history import ORIGINS

    out: dict[str, dict] = {}
    bodies: dict[str, set] = defaultdict(set)
    for e in entries:
        src = "history" if e.get("origin") in ORIGINS or e.get("source") in ORIGINS else e.get("source")
        lv = out.setdefault(src, {"fetches": 0, "responses": 0, "failed": 0, "refused": 0, "wayback": 0,
                                  "first_at": None, "last_at": None})
        lv["responses"] += 1
        if e.get("role") != "part":
            lv["fetches"] += 1
        if e.get("origin") == "wayback":
            lv["wayback"] += 1
        if e.get("status") != 200:
            lv["failed"] += 1
        if e.get("status") in REFUSED:
            lv["refused"] += 1
        if e.get("sha256"):
            bodies[src].add(e["sha256"])
        at = e.get("fetched_at")
        if at:
            lv["first_at"] = min(lv["first_at"] or at, at)
            lv["last_at"] = max(lv["last_at"] or at, at)
    for src, lv in out.items():
        lv["bodies"] = len(bodies[src])
    return out


def fetch_nights(entries: list[dict]) -> list[tuple]:
    """(night, source, responses, failed, refused) for every live fetch: what each source's scrape
    actually got back, which the run log does not say for the pages a fetch combines."""
    tally: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0, 0])
    for e in entries:
        if e.get("origin", "live") != "live":
            continue
        night = night_of(e.get("fetched_at"))
        if not night:
            continue
        t = tally[(night, e["source"])]
        t[0] += 1
        t[1] += int(e.get("status") != 200)
        t[2] += int(e.get("status") in REFUSED)
    return [(n, s, *v) for (n, s), v in sorted(tally.items())]


def publishes(root: Path, limit: int = 400) -> list[dict]:
    """The snapshot's commits on the checked-out branch, newest first: each one a publish to the site.
    Empty where there is no git (a copy of the code without its history)."""
    return list(_publishes(str(root), limit))


@lru_cache(maxsize=4)
def _publishes(root: str, limit: int) -> tuple[dict, ...]:   # one git call per process: a build's history does not move under it
    try:
        out = subprocess.run(["git", "-C", root, "log", f"-n{limit}", "--format=%H%x1f%cI%x1f%s", "--",
                              "web/public/data/manifest.json"], capture_output=True, text=True, timeout=30, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return ()
    rows = []
    for line in out.splitlines():
        parts = line.split("\x1f")
        if len(parts) == 3:
            rows.append({"sha": parts[0][:10], "at": parts[1], "subject": parts[2]})
    return tuple(rows)


def commit_of(root: Path) -> str | None:
    try:
        return subprocess.run(["git", "-C", str(root), "rev-parse", "--short=10", "HEAD"], capture_output=True, text=True,
                              timeout=10, check=True).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def build_record(report, mode: str, started_at: str, finished_at: str, root: Path, snapshot: dict | None) -> dict:
    """One line of the build log: what this build read and made."""
    return {"stage": "build", "mode": mode, "started_at": started_at, "finished_at": finished_at,
            "seconds": round(report.seconds, 1), "commit": commit_of(root),
            "fetches": report.fetches, "parsed": report.parsed, "from_cache": report.from_cache,
            "records": report.records, "sightings": report.sightings, "record_spans": report.record_spans,
            "unparsed": len(report.failures), "snapshot": snapshot or {}}


def page(conn, this_build: dict | None, exported: dict[str, dict[str, int]], today: str | None = None) -> dict:
    """The Data page's pipeline section: `levels` (one row per source) and `nights` (newest first, each
    night's scrapes per source, its builds and its publishes)."""
    levels = []
    for r in conn.execute("SELECT provider, payload FROM source_levels ORDER BY provider"):
        lv = json.loads(r["payload"])
        lv["provider"] = r["provider"]
        lv["describes_models"] = r["provider"] in DESCRIBES_MODELS
        lv["in_snapshot"] = exported.get(r["provider"], {})
        levels.append(lv)

    nights: dict[str, dict] = {}

    def night(label: str) -> dict:
        return nights.setdefault(label, {"night": label, "scrapes": {}, "builds": [], "publishes": []})

    def scrape(label: str, source: str) -> dict:
        return night(label)["scrapes"].setdefault(source, {
            "source": source, "capabilities": [], "runs": 0, "started_at": None, "finished_at": None, "status": None,
            "fetches": 0, "records": 0, "errors": 0, "skipped": 0, "deferred": 0, "responses": 0, "failed": 0, "refused": 0,
            "allowance": None})

    for r in conn.execute("SELECT * FROM runs ORDER BY started_at"):
        label = night_of(r["started_at"])
        if not label:
            continue
        cur = scrape(label, r["source"])
        if r["capability"] not in cur["capabilities"]:
            cur["capabilities"].append(r["capability"])
        cur["runs"] += 1
        cur["started_at"] = min(cur["started_at"] or r["started_at"], r["started_at"])
        cur["finished_at"] = max(cur["finished_at"] or "", r["finished_at"] or "") or None
        for k, col in (("fetches", "artifacts"), ("records", "records"), ("errors", "errors"), ("skipped", "skipped"), ("deferred", "deferred")):
            cur[k] += r[col] or 0
        # The night's worst: an error over a refusal over ok.
        rank = {"ok": 0, "refused": 1, "error": 2}
        if cur["status"] is None or rank.get(r["status"], 2) > rank.get(cur["status"], 2):
            cur["status"] = r["status"]
        if r["allowance"]:
            cur["allowance"] = json.loads(r["allowance"])
    # What came back, from the index: a run's own count is the pages it asked for, not what was refused,
    # and a fetch that combines several pages counts once there.
    for r in conn.execute("SELECT * FROM fetch_nights"):
        cur = scrape(r["night"], r["source"])
        cur["responses"] += r["responses"]
        cur["failed"] += r["failed"]
        cur["refused"] += r["refused"]
    builds = [json.loads(r["payload"]) for r in conn.execute("SELECT payload FROM builds ORDER BY finished_at")]
    if this_build:
        builds.append({**this_build, "this": True})
    for b in builds:
        label = night_of(b.get("started_at"))
        if label:
            night(label)["builds"].append(b)
    for r in conn.execute("SELECT sha, at, subject FROM publishes ORDER BY at"):
        label = night_of(r["at"])
        if label:
            night(label)["publishes"].append(dict(r))
    out = []
    for label in sorted(nights, reverse=True)[:NIGHTS_KEPT]:
        n = nights[label]
        out.append({"night": label, "scrapes": sorted(n["scrapes"].values(), key=lambda s: s["source"]),
                    "builds": n["builds"], "publishes": n["publishes"]})
    return {"levels": levels, "nights": out}
