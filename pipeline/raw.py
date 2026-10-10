"""The raw store: every response ever fetched, kept exactly as it came, forever.

It lives outside git, on the owner's laptop (`CAR_RESEARCH_RAW`, e.g.
D:\\car-research-raw). Everything else the pipeline holds is derived from it by a
process that can be re-run from scratch (docs/REBUILD.md).

    bodies/<sha[:2]>/<sha256>.gz    one gzipped file per distinct body, named by the
                                    sha256 of the uncompressed bytes; written once
    index/<YYYY-MM>.jsonl           one line per fetch, appended, never rewritten
    logs/<kind>-<YYYY-MM>.jsonl     what the scraper did: runs (the Data page's run log) and the
                                    Wayback backfill's finished pages; appended, never rewritten

An index line says what was fetched and when: source, capability, target (with the
metadata the parser needs to read the page again), url, fetched_at, status, sha256,
content type, size, and where it came from (`origin`: live, legacy, ...). A fetch
that failed is logged too, with its error and no body. An unchanged page fetched
again adds an index line and no body, so it costs a few hundred bytes and still
records that the page said the same thing on that date.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

ENV = "CAR_RESEARCH_RAW"
README = """car-research raw store

Every response the car-research pipeline has fetched, exactly as it came. Nothing
here is ever rewritten or deleted: the pipeline re-derives everything else from it.

  bodies/<sha[:2]>/<sha256>.gz   one gzipped file per distinct body
  index/<YYYY-MM>.jsonl          one line per fetch (what, when, which body)

Back this folder up. It is the only copy of the past.
Code and docs: https://github.com/TristanDickson/car-research (docs/REBUILD.md).
"""


def default_root() -> Path:
    return Path(os.environ.get(ENV) or Path.home() / "car-research-raw")


def sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def fetch_id(entry: dict) -> str:
    """A fetch's stable id: the same fetch imported twice is one fetch."""
    key = "|".join(str(entry.get(k) or "") for k in ("origin", "source", "capability", "target", "url", "fetched_at", "sha256"))
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]


@dataclass
class RawStore:
    root: Path

    @classmethod
    def open(cls, root: Path | str | None = None) -> "RawStore":
        store = cls(Path(root) if root else default_root())
        (store.root / "bodies").mkdir(parents=True, exist_ok=True)
        (store.root / "index").mkdir(parents=True, exist_ok=True)
        readme = store.root / "README.txt"
        if not readme.exists():
            readme.write_text(README, encoding="utf-8")
        return store

    def body_path(self, sha: str) -> Path:
        return self.root / "bodies" / sha[:2] / f"{sha}.gz"

    def has(self, sha: str) -> bool:
        return self.body_path(sha).exists()

    def put(self, body: bytes) -> str:
        """Store a body once; returns its sha256."""
        sha = sha256(body)
        path = self.body_path(sha)
        if path.exists():
            return sha
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp.write_bytes(gzip.compress(body, compresslevel=6, mtime=0))
        os.replace(tmp, path)
        return sha

    def get(self, sha: str) -> bytes:
        body = gzip.decompress(self.body_path(sha).read_bytes())
        if sha256(body) != sha:
            raise ValueError(f"raw body {sha} does not match its name")
        return body

    def record(self, entry: dict) -> dict:
        """Append one fetch to the index. `fetched_at` (ISO, UTC) picks the month file."""
        entry = {k: v for k, v in entry.items() if v is not None}
        entry.setdefault("origin", "live")
        entry["id"] = fetch_id(entry)
        line = json.dumps(entry, ensure_ascii=False, sort_keys=True)
        path = self.root / "index" / f"{entry['fetched_at'][:7]}.jsonl"
        with path.open("a", encoding="utf-8", newline="\n") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())
        return entry

    def save(self, *, source: str, capability: str, target: str, metadata: dict | None, url: str | None,
             fetched_at: str, status: int | None, body: bytes | None, content_type: str | None = None,
             error: str | None = None, origin: str = "live", note: str | None = None, role: str | None = None) -> dict:
        """Keep one fetch: the body (if any) and its index line. `role` 'part' marks one of the responses a
        combined fetch was made of (kept as it came; the build parses the combined body)."""
        sha = self.put(body) if body is not None else None
        return self.record({
            "source": source, "capability": capability, "target": target, "metadata": metadata or None,
            "url": url, "fetched_at": fetched_at, "status": status, "sha256": sha,
            "size": len(body) if body is not None else None, "content_type": content_type,
            "error": error, "origin": origin, "note": note, "role": role,
        })

    def log(self, kind: str, entry: dict) -> None:
        """Append one line to a log (runs, backfill): bookkeeping about the fetching, kept beside it."""
        stamp = entry.get("finished_at") or entry.get("done_at") or entry.get("started_at") or ""
        path = self.root / "logs" / f"{kind}-{stamp[:7] or 'undated'}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def log_run(self, entry: dict) -> None:
        self.log("runs", entry)

    def read_log(self, kind: str) -> Iterator[dict]:
        for path in sorted((self.root / "logs").glob(f"{kind}-*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    yield json.loads(line)

    def entries(self) -> Iterator[dict]:
        """Every fetch, oldest first (by fetched_at, then by position in the index)."""
        rows: list[tuple[str, int, dict]] = []
        n = 0
        for path in sorted((self.root / "index").glob("*.jsonl")):
            with path.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        e = json.loads(line)
                        rows.append((e["fetched_at"], n, e))
                        n += 1
        rows.sort(key=lambda r: (r[0], r[1]))
        seen: set[str] = set()
        for _, _, e in rows:
            if e["id"] in seen:
                continue
            seen.add(e["id"])
            yield e

    def ids(self) -> set[str]:
        return {e["id"] for e in self.entries()}
