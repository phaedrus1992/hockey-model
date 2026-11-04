"""The NHL steps of a refresh: score days, then boxscores."""

from datetime import UTC, date, datetime, timedelta

from hockey_model.game_day import game_day_of
from hockey_model.sources.nhl import (
    FINAL_STATES,
    boxscore_url,
    fetch_boxscore,
    fetch_score_day,
    score_day_url,
)
from hockey_model.store.nhl_writes import games_missing_boxscore, write_boxscore, write_games
from hockey_model.store.refresh_context import MAX_UNIT_FAILURES, RefreshRun
from hockey_model.store.source_reads import failed_since, failed_urls, last_ok_read
from hockey_model.store.timestamps import parse_iso_utc

SCORES = "nhl_scores"
BOXSCORES = "nhl_boxscores"
# A day is complete when a read came this long after the day began. The latest NHL game of a
# day ends before 12:00 UTC on the next day.
DAY_COMPLETE_AFTER = timedelta(hours=36)
# Without a stored game or a backfill date, a refresh starts this far back.
DEFAULT_LOOKBACK = timedelta(days=7)
# A refresh starts this long before the newest final game, to catch a game that was in progress.
OVERLAP = timedelta(days=1)
# A boxscore that failed to read is tried again after this long. Until then the next game
# goes first, so one bad game does not block the rest.
RETRY_FAILED_AFTER = timedelta(days=1)
# Days ahead of today that a refresh reads, for the schedule.
SCHEDULE_DAYS_AHEAD = 2
# A score day whose newest read failed is read again by every refresh in this window. A day
# that stays broken for longer, such as a preseason day, is left to the report of its first
# failure so that it does not fail every refresh for good.
FAILED_DAY_RETRY_WINDOW = timedelta(days=30)


def _failed_days(run: RefreshRun) -> list[date]:
    """Return the recent score days whose newest read failed."""
    oldest = game_day_of(run.now - FAILED_DAY_RETRY_WINDOW)
    days = (date.fromisoformat(url.rsplit("/", 1)[1]) for url in failed_urls(run.conn, SCORES))
    return [day for day in days if day >= oldest]


def _first_day(run: RefreshRun) -> date:
    if run.backfill_from is not None:
        return run.backfill_from
    marks = ",".join("?" for _ in FINAL_STATES)
    (newest,) = run.conn.execute(
        f"SELECT MAX(start_utc) FROM games WHERE state IN ({marks})", sorted(FINAL_STATES)
    ).fetchone()
    if newest is None:
        return game_day_of(run.now - DEFAULT_LOOKBACK)
    return min([game_day_of(parse_iso_utc(newest) - OVERLAP), *_failed_days(run)])


def _day_complete(run: RefreshRun, day: date) -> bool:
    last = last_ok_read(run.conn, SCORES, score_day_url(day))
    day_start = datetime(day.year, day.month, day.day, tzinfo=UTC)
    return last is not None and last >= day_start + DAY_COMPLETE_AFTER


def score_days(run: RefreshRun) -> None:
    """Read each score day from the first day through the schedule horizon.

    A day that was read after it ended is complete and is not read again.
    """
    last_day = game_day_of(run.now) + timedelta(days=SCHEDULE_DAYS_AHEAD)
    day = _first_day(run)
    failures = 0
    while day <= last_day:
        if failures >= MAX_UNIT_FAILURES:
            left = (last_day - day).days + 1
            run.notes.append(f"{SCORES}: stopped after {failures} failed days; {left} not tried")
            return
        if _day_complete(run, day):
            failures = 0
        else:
            current = day

            def unit(stamp: datetime, current: date = current) -> int:
                return write_games(run.conn, fetch_score_day(run.client, current), stamp)

            failures = 0 if run.attempt(SCORES, score_day_url(day), unit) else failures + 1
        day += timedelta(days=1)


def boxscores(run: RefreshRun) -> None:
    """Read the boxscore of each final game that has none. Each game is its own unit."""
    failures = 0
    skipped = 0
    waiting = games_missing_boxscore(run.conn)
    for index, game_id in enumerate(waiting):
        if failures >= MAX_UNIT_FAILURES:
            left = len(waiting) - index
            run.notes.append(
                f"{BOXSCORES}: stopped after {failures} failed reads; {left} not tried"
            )
            break
        url = boxscore_url(game_id)
        if failed_since(run.conn, BOXSCORES, url, run.now - RETRY_FAILED_AFTER):
            skipped += 1
            continue

        def unit(stamp: datetime, game_id: int = game_id) -> int:
            write_boxscore(run.conn, game_id, fetch_boxscore(run.client, game_id), stamp)
            return 1

        failures = 0 if run.attempt(BOXSCORES, url, unit) else failures + 1
    if skipped:
        run.notes.append(
            f"{BOXSCORES}: {skipped} skipped, because the last read failed a day ago or less"
        )
