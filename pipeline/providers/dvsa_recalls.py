"""DVSA's vehicle safety recalls (check-vehicle-recalls.service.gov.uk): every recall in Great Britain
since 1992, in the one file the service links as "All recalls since 1992 (CSV)".

The service answers a script with a JavaScript check and a browser with the file, so the fetch asks the
installed Chrome to download it (scripts/fetch-with-chrome.mjs: Chrome started normally, with a profile
of its own; nothing faked; about 15 s). One row per recall and model line: the launch date, the recall
number (R/2024/164), the make as the importer names itself ('VW', 'MERCEDES-BENZ CARS UK LTD'), the
model as the maker wrote it ('IONIQ 5', 'KONA OS EV', 'Kona SX2 1.0 T GDI'), the concern, the defect, the
remedy, the vehicles affected, the maker's reference, and the VIN and build ranges. Read: every row
launched since 2012 whose make is not a lorry, bus, motorcycle or caravan maker. Left: those, the older
rows and the VIN ranges. A recall that follows one that did not hold says so in its text ("recall
R/2023/154 has been incorrectly completed"); the build links them.

The build lays the rows over the catalogue's models (services/claims.py, from_recalls). Emits one 'spec'
record, dvsa:recalls, holding every row read. One file a night (7.7 MB, kept when it changes).
"""
from __future__ import annotations

import csv
import io
import re
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from datetime import date
from pathlib import Path

from pipeline.providers.http import FetchError
from pipeline.providers.types import Capability, Context, Fetched, ParsedRecord, Provider, Target
from pipeline.providers.wayback import observed_at_for

SITE = "dvsa"
URL = "https://www.check-vehicle-recalls.service.gov.uk/documents/RecallsFile.csv"
SINCE = 2012
NOT_CARS = re.compile(r"truck|\bbus\b|motorrad|motorcycle|caravan|trailer|coach|tabbert|adria|swift", re.I)


def discover(target: Target, ctx: Context) -> Iterator[Target]:
    if target.identifier in ("all", "recalls"):
        yield Target(identifier="recalls", metadata={"url": URL})


def fetch(target: Target, ctx: Context) -> Fetched:
    node = shutil.which("node")
    script = Path(ctx.root) / "scripts" / "fetch-with-chrome.mjs"
    if not node or not script.exists():
        raise FetchError(f"{URL}: needs node and {script} to have Chrome download it", url=URL)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "RecallsFile.csv"
        run = subprocess.run([node, str(script), target.metadata["url"], str(out)], capture_output=True, text=True, timeout=120)
        if run.returncode != 0 or not out.exists():
            raise FetchError(f"{URL}: Chrome did not download it (exit {run.returncode}): {(run.stderr or run.stdout).strip()[-300:]}", url=URL)
        return Fetched(url=target.metadata["url"], status_code=200, body=out.read_bytes(), content_type="text/csv")


def _iso(d: str | None) -> str | None:
    m = re.fullmatch(r"(\d\d)/(\d\d)/(\d{4})", (d or "").strip())
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
    except ValueError:
        return None


def parse_file(text: str) -> list[dict]:
    """The recall lines the build lays over the catalogue, as printed, with ISO dates."""
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        launched = _iso(r.get("Launch Date"))
        if not launched or int(launched[:4]) < SINCE or NOT_CARS.search(r.get("Make") or ""):
            continue
        vehicles = re.sub(r"\D", "", r.get("Vehicle Numbers") or "")
        out.append({
            "number": (r.get("Recalls Number") or "").strip(), "launched": launched, "make": (r.get("Make") or "").strip(),
            "model": (r.get("Model") or "").strip() or (r.get("Recalls Model Information") or "").strip(),
            "model_info": (r.get("Recalls Model Information") or "").strip(),
            "concern": (r.get("Concern") or "").strip(), "defect": (r.get("Defect") or "").strip(), "remedy": (r.get("Remedy") or "").strip(),
            "vehicles": int(vehicles) if vehicles else None, "maker_ref": (r.get("Manufacturer Ref") or "").strip() or None,
            "built_from": _iso(r.get("Build Start")), "built_to": _iso(r.get("Build End")),
        })
    return out


def parse(body: bytes, target: Target) -> Iterator[ParsedRecord]:
    rows = parse_file(body.decode("utf-8-sig", "replace"))
    if rows:
        yield ParsedRecord(kind="spec", key="dvsa:recalls", row={"spec_key": "dvsa:recalls", "source_url": target.metadata.get("url"),
                                                                 "observed_at": observed_at_for(target), "recalls": rows})


recalls = Capability(name="recalls", parser_version="1", discover=discover, fetch=fetch, parse=parse, kinds=("spec",))
provider = Provider(name="dvsa_recalls", default_capability="recalls", capabilities={"recalls": recalls}, live=True)
