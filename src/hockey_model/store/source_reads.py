"""Record which source reads worked and which failed."""

import sqlite3
from datetime import datetime

from hockey_model.store.timestamps import iso_utc, parse_iso_utc

# Every source name that a refresh records in ``source_reads``.
KNOWN_SOURCES = frozenset(
    {"nhl_scores", "nhl_boxscores", "moneypuck", "espn_starters", "espn_injuries", "daily_faceoff"}
)
# A URL whose last this-many reads all failed is a known gap. A refresh skips it and says so.
ABANDON_AFTER_FAILED_READS = 2
# The failed reads must span at least this long, so one outage does not make a gap.
ABANDON_MIN_SPAN_DAYS = 0.5
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


def failed_urls(conn: sqlite3.Connection, source: str) -> list[str]:
    """Return the URLs of ``source`` whose newest read failed, in name order."""
    cursor = conn.execute(
        "SELECT r.url FROM source_reads r JOIN"
        " (SELECT url, MAX(fetched_at) AS newest FROM source_reads WHERE source = ?"
        "  GROUP BY url) n ON r.url = n.url AND r.fetched_at = n.newest"
        " WHERE r.source = ? AND r.ok = 0 ORDER BY r.url",
        (source, source),
    )
    return [url for (url,) in cursor]


def stale_sources(conn: sqlite3.Connection, as_of: datetime) -> list[tuple[str, str]]:
    """Return ``(source, reason)`` for each known source that is not current at ``as_of``.

    A source is not current when its newest read before ``as_of`` failed, or when no read
    of it has worked yet. The result is in name order.
    """
    cursor = conn.execute(
        "SELECT source, MAX(fetched_at), MAX(CASE WHEN ok = 1 THEN fetched_at END)"
        " FROM source_reads WHERE fetched_at <= ? GROUP BY source",
        (iso_utc(as_of),),
    )
    reads = {source: (newest, good) for source, newest, good in cursor}
    stale: list[tuple[str, str]] = []
    for source in sorted(KNOWN_SOURCES):
        newest, good = reads.get(source, (None, None))
        if good is None:
            stale.append((source, "no read of it has worked yet"))
        elif newest != good:
            stale.append((source, "the newest read of it failed"))
    return stale


def abandoned_urls(conn: sqlite3.Connection, source: str) -> frozenset[str]:
    """Return the URLs of ``source`` whose reads failed ``ABANDON_AFTER_FAILED_READS`` times
    in a row, with no good read between them, over at least ``ABANDON_MIN_SPAN_DAYS``."""
    cursor = conn.execute(
        "SELECT r.url FROM source_reads r WHERE r.source = ? AND r.ok = 0 AND r.fetched_at >"
        " COALESCE((SELECT MAX(o.fetched_at) FROM source_reads o"
        "           WHERE o.source = r.source AND o.url = r.url AND o.ok = 1), '')"
        " GROUP BY r.url HAVING COUNT(*) >= ?"
        " AND julianday(MAX(r.fetched_at)) - julianday(MIN(r.fetched_at)) >= ?",
        (source, ABANDON_AFTER_FAILED_READS, ABANDON_MIN_SPAN_DAYS),
    )
    return frozenset(url for (url,) in cursor)
