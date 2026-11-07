"""The NHL steps of a backfill: one year at a time, newest year first."""

from collections.abc import Iterator
from datetime import date, timedelta

from hockey_model.game_day import game_day_of
from hockey_model.store.nhl_writes import games_missing_boxscore
from hockey_model.store.refresh_context import RefreshRun
from hockey_model.store.refresh_nhl import (
    SCHEDULE_DAYS_AHEAD,
    note_unresolved,
    plan_unresolved,
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


def _budget_stall_error() -> HockeyModelError:
    """Return the error for a run that the time budget stopped before it finished any unit.

    Every later run with the same budget reads the same open days and stops at the same place,
    so the backfill never finishes. The error makes the run exit 1 instead of 75.
    """
    return HockeyModelError(
        "refresh: the backfill spent its time budget before it finished one new day or game, "
        "so it cannot make progress; give --budget-seconds a larger value "
        "(BACKFILL_BUDGET_S in scripts/daily-prepare.sh)"
    )


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
    unresolved, due = plan_unresolved(run)
    complete = True
    stopped = False
    progress = 0
    for start, end in windows(run.backfill_from, last_day):
        days = {start + timedelta(days=n) for n in range((end - start).days + 1)}
        window_due = [day for day in due if start <= day <= end]
        days_read = read_days(run, sorted(days | set(window_due)), gaps, window_due)
        boxes = read_boxscores(run, games_missing_boxscore(run.conn, start, end))
        complete = complete and days_read.clean and boxes.clean
        progress += days_read.progress + boxes.progress
        if days_read.stopped or boxes.stopped:
            run.notes.append(f"backfill: stopped in the window {start} to {end}")
            stopped = True
            break
    if not complete:
        run.notes.append("backfill: some days or games are unread; run it again")
    if stopped and progress == 0 and run.out_of_time():
        run.errors.append(_budget_stall_error())
    note_unresolved(run, unresolved)
    run.backfill_complete = complete
