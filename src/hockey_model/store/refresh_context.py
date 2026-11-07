"""The state that one refresh shares across its sources."""

import sqlite3
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime

from hockey_model.sources.errors import SourceError
from hockey_model.sources.http import HttpClient
from hockey_model.sources.shape_errors import SourceParseError, SourceShapeError
from hockey_model.store.db import StoreError
from hockey_model.store.source_reads import record_read
from hockey_model.types import HockeyModelError

# Errors that a bad source response or a bad stored schedule cause. Other errors are bugs.
SOURCE_FAILURES = (SourceError, SourceShapeError, SourceParseError, StoreError)
# A source that fails this many units in a row stops, so a dead host does not cost hours.
MAX_UNIT_FAILURES = 3


@dataclass(frozen=True, slots=True)
class RefreshReport:
    """What one refresh wrote, what failed, and what the reader of the data must credit."""

    written: dict[str, int]
    errors: tuple[HockeyModelError, ...]
    notes: tuple[str, ...]
    credits: tuple[str, ...]
    # True when a backfill read every window, False when it stopped early, None without one.
    backfill_complete: bool | None = None


@dataclass
class RefreshRun:
    """One refresh in progress. A source runs its work in units through ``attempt``."""

    conn: sqlite3.Connection
    client: HttpClient
    now: datetime
    backfill_from: date | None = None
    clock: Callable[[], datetime] | None = None
    deadline: datetime | None = None
    backfill_complete: bool | None = None
    written: Counter[str] = field(default_factory=Counter)
    errors: list[HockeyModelError] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    # Read the MoneyPuck files even when they are fresh. The upgrade needs this so the
    # attempt counts arrive at once, instead of after the weekly refresh.
    reread_moneypuck: bool = False
    credits: list[str] = field(default_factory=list)

    def stamp(self) -> datetime:
        """Return the time to store with a read: the clock when one is set, else ``now``."""
        return self.now if self.clock is None else self.clock()

    def out_of_time(self) -> bool:
        """Return True once the time budget of this refresh is spent."""
        return self.deadline is not None and self.stamp() >= self.deadline

    def attempt(self, source: str, url: str, unit: Callable[[datetime], int]) -> bool:
        """Run one unit of work in one transaction. Return False when it failed.

        A failed unit writes nothing, adds its error to the report, and leaves a
        ``source_reads`` row with ``ok = 0``. The unit returns the rows it wrote.
        """
        stamp = self.stamp()
        try:
            with self.conn:
                written = unit(stamp)
                record_read(self.conn, source, url, stamp)
        except SOURCE_FAILURES as exc:
            with self.conn:
                record_read(self.conn, source, url, stamp, error=str(exc))
            self.errors.append(exc)
            return False
        self.written[source] += written
        return True

    def report(self) -> RefreshReport:
        """Return the final report of this run."""
        return RefreshReport(
            dict(self.written),
            tuple(self.errors),
            tuple(self.notes),
            tuple(self.credits),
            self.backfill_complete,
        )
