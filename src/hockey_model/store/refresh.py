"""Fill the store from every source. The prediction call reads the store and fetches nothing."""

import sqlite3
from collections.abc import Callable
from datetime import date, datetime

from hockey_model.sources.http import HttpClient
from hockey_model.store.refresh_context import RefreshReport, RefreshRun
from hockey_model.store.refresh_nhl import boxscores, score_days
from hockey_model.store.refresh_other import daily_faceoff, espn_injuries, espn_starters, moneypuck

_STEPS = (score_days, boxscores, moneypuck, espn_starters, espn_injuries, daily_faceoff)

__all__ = ["RefreshReport", "refresh"]


def refresh(
    conn: sqlite3.Connection,
    client: HttpClient,
    *,
    now: datetime,
    backfill_from: date | None = None,
    clock: Callable[[], datetime] | None = None,
) -> RefreshReport:
    """Read every source in order, and report what was written and what failed.

    Each source runs even when an earlier one failed. A failed unit of work writes nothing.
    ``clock`` stamps each read with its own fetch time. Without it, every read gets ``now``.
    """
    if now.tzinfo is None:
        raise ValueError(f"refresh: now {now!r} has no timezone; pass a UTC datetime")
    run = RefreshRun(conn, client, now, backfill_from, clock)
    for step in _STEPS:
        step(run)
    return run.report()
