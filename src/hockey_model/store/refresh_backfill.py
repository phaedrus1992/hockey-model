"""The NHL steps of a backfill: one year at a time, newest year first."""

from collections.abc import Iterator
from datetime import date, timedelta

from hockey_model.game_day import game_day_of
from hockey_model.store.nhl_writes import games_missing_boxscore
from hockey_model.store.refresh_context import RefreshRun
from hockey_model.store.refresh_nhl import (
    SCHEDULE_DAYS_AHEAD,
    boxscores,
    read_boxscores,
    read_days,
    score_days,
    score_gaps,
)

# A backfill reads this many game days at a time. A refresh that spends its time budget
# leaves the older windows for the next run.
WINDOW_DAYS = 365


def windows(first: date, last: date) -> Iterator[tuple[date, date]]:
    """Yield ``(start, end)`` game-day windows from ``last`` back to ``first``, newest first.

    Both ends are included, and the windows do not overlap.
    """
    end = last
    while end >= first:
        start = max(first, end - timedelta(days=WINDOW_DAYS - 1))
        yield start, end
        end = start - timedelta(days=1)


def nhl(run: RefreshRun) -> None:
    """Read the score days and the boxscores. A backfill reads them window by window."""
    if run.backfill_from is None:
        score_days(run)
        boxscores(run)
        return
    last_day = game_day_of(run.now) + timedelta(days=SCHEDULE_DAYS_AHEAD)
    gaps = score_gaps(run)
    for start, end in windows(run.backfill_from, last_day):
        days_read = read_days(run, start, end, gaps)
        boxes_read = read_boxscores(run, games_missing_boxscore(run.conn, start, end))
        if not (days_read and boxes_read):
            run.notes.append(f"backfill: stopped in the window {start} to {end}; run it again")
            run.backfill_complete = False
            return
    run.backfill_complete = True
