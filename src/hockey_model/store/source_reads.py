"""Record which source reads worked and which failed."""

import sqlite3
from datetime import datetime

from hockey_model.store.timestamps import iso_utc, parse_iso_utc

# The source name of the ESPN injury list. Each good read of the list is one snapshot.
ESPN_INJURIES = "espn_injuries"


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


def stale_sources(conn: sqlite3.Connection, as_of: datetime) -> list[str]:
    """Return the sources whose newest read before ``as_of`` failed, in name order."""
    cursor = conn.execute(
        "SELECT r.source FROM source_reads r JOIN (SELECT source, MAX(fetched_at) AS latest"
        " FROM source_reads WHERE fetched_at <= ? GROUP BY source) n"
        " ON r.source = n.source AND r.fetched_at = n.latest WHERE r.ok = 0"
        " GROUP BY r.source ORDER BY r.source",
        (iso_utc(as_of),),
    )
    return [row[0] for row in cursor]
