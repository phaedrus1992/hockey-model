"""The NHL steps of a refresh: score days, then boxscores."""

import sqlite3
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import NamedTuple

from hockey_model.game_day import game_day_of
from hockey_model.sources.nhl import (
    FINAL_STATES,
    BoxscoreRows,
    boxscore_url,
    fetch_boxscore,
    fetch_score_day,
    score_day_url,
)
from hockey_model.sources.shape_errors import SourceParseError
from hockey_model.store.db import StoreError
from hockey_model.store.nhl_writes import write_boxscore, write_games
from hockey_model.store.reads import game_row, unresolved_games
from hockey_model.store.refresh_context import MAX_UNIT_FAILURES, RefreshRun
from hockey_model.store.source_reads import (
    abandoned_urls,
    failed_since,
    failed_urls,
    last_ok_read,
    newest_read,
)
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
# A game that started this long ago and has no final read is unresolved. A successful read of
# its day is not proof that the game finished: it can be suspended, moved, or still unknown.
UNRESOLVED_AFTER = DAY_COMPLETE_AFTER
# An unresolved game's day is read again after this long, and after the longer wait once the
# game is old, so a game that never resolves does not cost a request on every refresh.
UNRESOLVED_RETRY_AFTER = timedelta(days=1)
UNRESOLVED_OLD_AFTER = timedelta(days=14)
UNRESOLVED_OLD_RETRY_AFTER = timedelta(days=7)
# At most this many unresolved days are read again in one refresh, oldest first.
MAX_UNRESOLVED_DAYS = 10


def _day_of(url: str) -> date:
    """Return the day that a score URL reads."""
    try:
        return date.fromisoformat(url.rsplit("/", 1)[1])
    except ValueError as exc:
        raise StoreError(
            f"source_reads holds {url!r} for {SCORES}, which is not a score day"
        ) from exc


def _failed_days(run: RefreshRun) -> list[date]:
    """Return the recent score days whose newest read failed, except the known gaps."""
    oldest = game_day_of(run.now - FAILED_DAY_RETRY_WINDOW)
    skipped = abandoned_urls(run.conn, SCORES)
    days = (_day_of(url) for url in failed_urls(run.conn, SCORES) if url not in skipped)
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


def _unresolved_games(run: RefreshRun) -> list[tuple[int, datetime]]:
    """Return ``(game_id, start)`` of each game whose newest read is not final, oldest first.

    A game counts once it started more than ``UNRESOLVED_AFTER`` ago. A game that is still
    to come, or on today's slate, is covered by the normal window.
    """
    found = unresolved_games(run.conn, run.now - UNRESOLVED_AFTER)
    return [(game_id, start) for game_id, _, _, start in found]


def _unresolved_days_due(run: RefreshRun, games: list[tuple[int, datetime]]) -> list[date]:
    """Return the score days to read again for unresolved games, oldest first and bounded."""
    due: list[date] = []
    for _, start in games:
        day = game_day_of(start)
        if day in due:
            continue
        wait = (
            UNRESOLVED_OLD_RETRY_AFTER
            if run.now - start >= UNRESOLVED_OLD_AFTER
            else UNRESOLVED_RETRY_AFTER
        )
        last = newest_read(run.conn, SCORES, score_day_url(day))
        if last is None or run.now - last >= wait:
            due.append(day)
    return due[:MAX_UNRESOLVED_DAYS]


def _describe(items: list[str], shown: int = 5) -> str:
    """Name the first few items of a list, and count the rest."""
    names = ", ".join(items[:shown])
    return names if len(items) <= shown else f"{names} and {len(items) - shown} more"


def note_unresolved(run: RefreshRun, games: list[tuple[int, datetime]]) -> None:
    """Name the games that are still not final long after their start."""
    if not games:
        return
    names = _describe([str(game_id) for game_id, _ in games])
    run.notes.append(
        f"{SCORES}: {len(games)} game(s) are not final long after their start "
        f"({names}); each is read again after a wait"
    )


class ReadResult(NamedTuple):
    """How a read of days or games ended."""

    clean: bool  # every unit is read, or is a known gap
    stopped: bool  # the read quit early: three failures in a row, or the time ran out


def score_gaps(run: RefreshRun) -> set[date]:
    """Return the score days that failed in every recent read, and note them in the report."""
    skipped = sorted(_day_of(url) for url in abandoned_urls(run.conn, SCORES))
    if skipped:
        names = _describe([day.isoformat() for day in skipped])
        run.notes.append(f"{SCORES}: skipped {names}, which failed in every read")
    return set(skipped)


def plan_unresolved(run: RefreshRun) -> tuple[list[tuple[int, datetime]], list[date]]:
    """Return the unresolved games, and the score days to read again because of them."""
    unresolved = _unresolved_games(run)
    return unresolved, _unresolved_days_due(run, unresolved)


def read_days(
    run: RefreshRun, worklist: Sequence[date], gaps: set[date], due: Sequence[date] = ()
) -> ReadResult:
    """Read each score day of ``worklist``, in order.

    A day that was read after it ended is complete and is not read again, unless it is in
    ``due``. A day in ``gaps`` is a known gap, so it counts as read. The read stops when three
    days in a row fail or the time budget is spent.
    """
    failures = 0
    clean = True
    for index, day in enumerate(worklist):
        if failures >= MAX_UNIT_FAILURES:
            left = len(worklist) - index
            run.notes.append(f"{SCORES}: stopped after {failures} failed days; {left} not tried")
            return ReadResult(clean=False, stopped=True)
        if day in gaps or (day not in due and _day_complete(run, day)):
            failures = 0
            continue
        if run.out_of_time():
            run.notes.append(f"{SCORES}: stopped at {day.isoformat()}, because the time ran out")
            return ReadResult(clean=False, stopped=True)

        def unit(stamp: datetime, current: date = day) -> int:
            return write_games(run.conn, fetch_score_day(run.client, current), stamp)

        ok = run.attempt(SCORES, score_day_url(day), unit)
        failures = 0 if ok else failures + 1
        clean = clean and ok
    return ReadResult(clean, stopped=False)


def score_days(run: RefreshRun) -> None:
    """Read each score day from the first day through the schedule horizon.

    A day that was read after it ended is complete and is not read again. A day with an
    unresolved game is read again after a wait, even when newer games are final.
    """
    last_day = game_day_of(run.now) + timedelta(days=SCHEDULE_DAYS_AHEAD)
    first = _first_day(run)
    unresolved, due = plan_unresolved(run)
    window = (first + timedelta(days=n) for n in range((last_day - first).days + 1))
    read_days(run, sorted({*due, *window}), score_gaps(run), due)
    note_unresolved(run, unresolved)


def check_boxscore_identity(conn: sqlite3.Connection, game_id: int, rows: BoxscoreRows) -> None:
    """Raise unless the boxscore names the stored game's teams, home and away as stored.

    A reversed pair is a different game, so it is never read as equal. The check runs before
    any row is written.
    """
    stored = game_row(conn, game_id)
    if stored is None:
        raise SourceParseError(
            "nhl",
            f"boxscore for game {game_id} has no stored game to match; read the score day first",
        )
    if (rows.home, rows.away) != (stored.home, stored.away):
        raise SourceParseError(
            "nhl",
            f"boxscore for game {game_id} names {rows.away} at {rows.home}, but the stored game "
            f"is {stored.away} at {stored.home}",
        )


def read_boxscores(run: RefreshRun, game_ids: list[int]) -> ReadResult:
    """Read the boxscore of each game in ``game_ids``. Each game is its own unit.

    The result is clean when every game that is not a known gap now has its boxscore.
    """
    failures = 0
    skipped = 0
    clean = True
    gaps = abandoned_urls(run.conn, BOXSCORES)
    waiting = [g for g in game_ids if boxscore_url(g) not in gaps]
    if gaps:
        run.notes.append(f"{BOXSCORES}: {len(gaps)} games skipped, because every read failed")
    for index, game_id in enumerate(waiting):
        if failures >= MAX_UNIT_FAILURES:
            left = len(waiting) - index
            run.notes.append(
                f"{BOXSCORES}: stopped after {failures} failed reads; {left} not tried"
            )
            return ReadResult(clean=False, stopped=True)
        if run.out_of_time():
            left = len(waiting) - index
            run.notes.append(f"{BOXSCORES}: stopped, because the time ran out; {left} not tried")
            return ReadResult(clean=False, stopped=True)
        url = boxscore_url(game_id)
        if failed_since(run.conn, BOXSCORES, url, run.now - RETRY_FAILED_AFTER):
            skipped += 1
            clean = False
            continue

        def unit(stamp: datetime, game_id: int = game_id) -> int:
            rows = fetch_boxscore(run.client, game_id)
            check_boxscore_identity(run.conn, game_id, rows)
            write_boxscore(run.conn, game_id, rows, stamp)
            return 1

        ok = run.attempt(BOXSCORES, url, unit)
        failures = 0 if ok else failures + 1
        clean = clean and ok
    if skipped:
        run.notes.append(
            f"{BOXSCORES}: {skipped} skipped, because the last read failed a day ago or less"
        )
    return ReadResult(clean, stopped=False)
