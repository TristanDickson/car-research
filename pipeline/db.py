"""SQLite connection + schema. The DB is a dev-machine artifact (gitignored);
the committed thing is the snapshot the exporter writes from it."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "car-research.sqlite"
SCHEMA = Path(__file__).with_name("schema.sql")


def db_path() -> Path:
    return Path(os.environ.get("CAR_RESEARCH_DB", DEFAULT_DB))


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    p = Path(path) if path else db_path()
    if str(p) != ":memory:":
        p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if str(p) != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.commit()
