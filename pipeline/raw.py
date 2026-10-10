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
import sys
import time
from contextlib import contextmanager
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
        """Store a body once; returns its sha256. The bytes reach the disk before the file gets its
        name, and a file under that name that does not read back (a crash mid-write) is written again."""
        sha = sha256(body)
        path = self.body_path(sha)
        if path.exists():
            try:
                self.get(sha)
                return sha
            except Exception:  # noqa: BLE001 - unreadable or wrong: this fetch has the bytes, so repair it
                pass
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        with tmp.open("wb") as f:
            f.write(gzip.compress(body, compresslevel=6, mtime=0))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        return sha

    def get(self, sha: str) -> bytes:
        body = gzip.decompress(self.body_path(sha).read_bytes())
        if sha256(body) != sha:
            raise ValueError(f"raw body {sha} does not match its name")
        return body

    @contextmanager
    def _lock(self, timeout: float = 120.0) -> Iterator[None]:
        """One writer at a time across processes (the nightly and a hand-run scrape, say): appending is
        not atomic on Windows. A lock left by a killed process is taken over after ten minutes."""
        path = self.root / ".lock"
        deadline = time.monotonic() + timeout
        while True:
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                break
            except (FileExistsError, PermissionError):   # Windows: PermissionError while another process deletes it
                try:
                    if time.time() - path.stat().st_mtime > 600:
                        path.unlink()
                        continue
                except (FileNotFoundError, PermissionError):
                    pass
                if time.monotonic() > deadline:
                    raise TimeoutError(f"the raw store at {self.root} is locked ({path})")
                time.sleep(0.05)
        try:
            os.write(fd, str(os.getpid()).encode())
            yield
        finally:
            os.close(fd)
            try:
                path.unlink()
            except (FileNotFoundError, PermissionError):
                pass

    def _append(self, path: Path, line: str) -> None:
        """Append one line durably. If the file does not end in a newline (a write torn by a crash),
        start on a new line, so the torn line costs only itself."""
        path.parent.mkdir(parents=True, exist_ok=True)
        data = (line + "\n").encode("utf-8")
        with self._lock():
            with path.open("ab") as f:
                if f.tell() > 0:
                    with path.open("rb") as r:
                        r.seek(-1, os.SEEK_END)
                        if r.read(1) != b"\n":
                            data = b"\n" + data
                f.write(data)
                f.flush()
                os.fsync(f.fileno())

    def record(self, entry: dict) -> dict:
        """Append one fetch to the index. `fetched_at` (ISO, UTC) picks the month file."""
        entry = {k: v for k, v in entry.items() if v is not None}
        entry.setdefault("origin", "live")
        entry["id"] = fetch_id(entry)
        self._append(self.root / "index" / f"{entry['fetched_at'][:7]}.jsonl", json.dumps(entry, ensure_ascii=False, sort_keys=True))
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
        self._append(self.root / "logs" / f"{kind}-{stamp[:7] or 'undated'}.jsonl", json.dumps(entry, ensure_ascii=False, sort_keys=True))

    def log_run(self, entry: dict) -> None:
        self.log("runs", entry)

    @staticmethod
    def _lines(path: Path) -> Iterator[dict]:
        """A JSONL file's records; a line torn by a crash is reported and skipped, never fatal."""
        for i, line in enumerate(path.read_bytes().decode("utf-8", "replace").splitlines(), 1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except ValueError:
                print(f"raw store: {path.name} line {i} is unreadable (a torn write); skipped", file=sys.stderr)

    def read_log(self, kind: str) -> Iterator[dict]:
        for path in sorted((self.root / "logs").glob(f"{kind}-*.jsonl")):
            yield from self._lines(path)

    def entries(self) -> Iterator[dict]:
        """Every fetch, oldest first (by fetched_at, then by position in the index)."""
        rows: list[tuple[str, int, dict]] = []
        n = 0
        for path in sorted((self.root / "index").glob("*.jsonl")):
            for e in self._lines(path):
                if isinstance(e, dict) and e.get("id") and e.get("fetched_at"):
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
