"""Record which source reads worked and which failed."""

import sqlite3
from datetime import datetime

from hockey_model.store.timestamps import iso_utc, parse_iso_utc


def record_read(
    conn: sqlite3.Connection,
    source: str,
    url: str,
    fetched_at: datetime,
    error: str | None = None,
) -> None:
    """Append a row to ``source_reads``. ``error`` is ``None`` for a read that worked."""
    conn.execute(
        "INSERT INTO source_reads (source, url, fetched_at, ok, error) VALUES (?,?,?,?,?)",
        (source, url, iso_utc(fetched_at), int(error is None), error),
    )


def last_ok_read(conn: sqlite3.Connection, source: str, url: str) -> datetime | None:
    """Return the time of the newest read of ``url`` that worked, or ``None``."""
    row = conn.execute(
        "SELECT MAX(fetched_at) FROM source_reads WHERE source = ? AND url = ? AND ok = 1",
        (source, url),
    ).fetchone()
    return None if row[0] is None else parse_iso_utc(row[0])


def failed_since(conn: sqlite3.Connection, source: str, url: str, since: datetime) -> bool:
    """Return True when the newest read of ``url`` failed and came after ``since``."""
    row = conn.execute(
        "SELECT ok, fetched_at FROM source_reads WHERE source = ? AND url = ?"
        " ORDER BY fetched_at DESC LIMIT 1",
        (source, url),
    ).fetchone()
    return row is not None and not row[0] and parse_iso_utc(row[1]) > since
