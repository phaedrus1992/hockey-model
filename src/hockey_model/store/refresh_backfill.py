"""The NHL steps of a backfill: one year at a time, newest year first."""

from collections.abc import Iterator
from datetime import date, timedelta

from hockey_model.game_day import game_day_of
from hockey_model.store.nhl_writes import games_missing_boxscore
from hockey_model.store.refresh_context import RefreshRun
from hockey_model.store.refresh_nhl import (
    SCHEDULE_DAYS_AHEAD,
    read_boxscores,
    read_days,
    score_days,
    score_gaps,
)
from hockey_model.types import HockeyModelError

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
        read_boxscores(run, games_missing_boxscore(run.conn))
        return
    last_day = game_day_of(run.now) + timedelta(days=SCHEDULE_DAYS_AHEAD)
    if run.backfill_from > last_day:
        raise HockeyModelError(
            f"refresh: --backfill-from {run.backfill_from} is after {last_day}, the last day "
            "that the schedule reads; give an earlier date"
        )
    gaps = score_gaps(run)
    complete = True
    for start, end in windows(run.backfill_from, last_day):
        days = read_days(run, start, end, gaps)
        boxes = read_boxscores(run, games_missing_boxscore(run.conn, start, end))
        complete = complete and days.clean and boxes.clean
        if days.stopped or boxes.stopped:
            run.notes.append(f"backfill: stopped in the window {start} to {end}")
            break
    if not complete:
        run.notes.append("backfill: some days or games are unread; run it again")
    run.backfill_complete = complete
