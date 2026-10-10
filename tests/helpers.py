"""Shared test plumbing: a raw store in a temporary folder filled with the real captured
pages in tests/fixtures, and a build from scratch over it (and over the real seed and
pastes, which the build always reads). Nothing here touches the network."""
import sqlite3
import tempfile
from pathlib import Path

from pipeline.build import Build
from pipeline.db import ROOT, connect, init_schema
from pipeline.providers import PROVIDERS
from pipeline.providers.types import Context, Provider, Target
from pipeline.raw import RawStore

FIX = Path(__file__).parent / "fixtures"
T = "2026-10-08T00:00:00+00:00"


def fresh_conn() -> sqlite3.Connection:
    conn = connect(":memory:")
    init_schema(conn)
    return conn


def run_all(conn: sqlite3.Connection | None = None) -> sqlite3.Connection:
    """A build over the owner's own files only (the seed and the pastes)."""
    conn = conn or fresh_conn()
    Build(conn, None).run()
    return conn


def target_for(provider: Provider, capability: str | None, ident: str, db: sqlite3.Connection | None = None) -> Target:
    """The target the provider's own discovery yields for `ident` (its metadata is what the parser reads)."""
    cap = provider.capability_for(capability)
    ctx = Context(root=ROOT, extras={"db": db} if db is not None else {})
    for name in (ident, "all"):
        for t in cap.discover(Target(identifier=name), ctx):
            if t.identifier == ident:
                return t
    raise KeyError(f"{provider.name}/{cap.name} discovers no target {ident!r}")


class Raws:
    """A raw store in a temporary folder. `add` keeps one fetched page, `build` builds from scratch."""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = RawStore.open(self._tmp.name)

    def add(self, provider: str | Provider, ident: str, fixture: str | None = None, *, body: bytes | None = None,
            capability: str | None = None, at: str = T, metadata: dict | None = None, status: int = 200,
            db: sqlite3.Connection | None = None) -> dict:
        p = PROVIDERS[provider] if isinstance(provider, str) else provider
        cap = p.capability_for(capability)
        if metadata is None:
            metadata = target_for(p, cap.name, ident, db).metadata
        if body is None:
            body = (FIX / fixture).read_bytes()
        return self.store.save(source=p.name, capability=cap.name, target=ident, metadata=metadata, url=metadata.get("url"),
                               fetched_at=at, status=status, body=body)

    def build(self, conn: sqlite3.Connection | None = None) -> sqlite3.Connection:
        conn = conn or fresh_conn()
        Build(conn, self.store).run()
        return conn

    def close(self) -> None:
        self._tmp.cleanup()

    def __enter__(self) -> "Raws":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def dump(conn: sqlite3.Connection) -> dict[str, list[tuple]]:
    """Every table's rows, sorted: two builds from the same inputs must agree on all of it."""
    out = {}
    for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({name})") if r[1] != "id"]
        out[name] = sorted((tuple(r) for r in conn.execute(f"SELECT {', '.join(cols)} FROM {name}")), key=repr)
    return out
