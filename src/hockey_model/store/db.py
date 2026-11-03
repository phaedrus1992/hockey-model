"""Open the SQLite store and guard its schema version."""

import sqlite3
from collections.abc import Mapping
from pathlib import Path

from hockey_model.types import HockeyModelError

DB_ENV = "HOCKEY_MODEL_DB"
SCHEMA_VERSION = 1
_SCHEMA_PATH = Path(__file__).with_name("schema.sql")


class StoreError(HockeyModelError):
    """Raised when the database path is missing or the schema does not match."""


def db_path_from_env(environ: Mapping[str, str]) -> Path:
    """Return the database path named by ``HOCKEY_MODEL_DB``."""
    value = environ.get(DB_ENV, "")
    if not value.strip():
        raise StoreError(
            f"read {DB_ENV}: the variable is not set or is empty; "
            f"set {DB_ENV} to the path of the SQLite file"
        )
    return Path(value)


def connect(path: Path) -> sqlite3.Connection:
    """Open the store at ``path``, creating the file and schema on first use."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    if not _has_table(conn, "schema_version"):
        _create_schema(conn)
    stored = conn.execute("SELECT version FROM schema_version").fetchone()[0]
    if stored != SCHEMA_VERSION:
        conn.close()
        raise StoreError(
            f"open store {str(path)!r}: schema version {stored} does not match "
            f"expected {SCHEMA_VERSION}; use a store made by this version or a new path"
        )
    return conn


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone()
    return row is not None


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
    conn.commit()
