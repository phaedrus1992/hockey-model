"""The MoneyPuck, ESPN, and Daily Faceoff steps of a refresh."""

from datetime import date, datetime, timedelta

from hockey_model.sources.daily_faceoff import STARTERS_URL, fetch_starters
from hockey_model.sources.espn import ESPN_BASE, fetch_injuries, fetch_scoreboard_starters
from hockey_model.sources.moneypuck import (
    FIRST_SEASON,
    MONEYPUCK_CREDIT,
    REFRESH_AFTER,
    TEAM_GAMES_URL,
    fetch_goalie_games,
    fetch_team_games,
    goalie_games_url,
)
from hockey_model.sources.starters import StarterRead
from hockey_model.store.espn_writes import write_injury_reads
from hockey_model.store.moneypuck_writes import (
    last_moneypuck_fetch,
    write_goalie_games,
    write_team_games,
)
from hockey_model.store.refresh_context import MAX_UNIT_FAILURES, RefreshRun
from hockey_model.store.starter_writes import write_starter_reads

MONEYPUCK = "moneypuck"
ESPN_STARTERS = "espn_starters"
ESPN_INJURIES = "espn_injuries"
DAILY_FACEOFF = "daily_faceoff"
# NHL seasons start in the fall, so July is a safe month to count the new season from.
_SEASON_STARTS_IN_MONTH = 7
_UNMATCHED_SHOWN = 5


def current_season_start(now: datetime) -> int:
    """Return the first year of the season that ``now`` falls in."""
    return now.year if now.month >= _SEASON_STARTS_IN_MONTH else now.year - 1


def _stale(run: RefreshRun, url: str, *, refresh_weekly: bool) -> bool:
    last = last_moneypuck_fetch(run.conn, url)
    if last is None:
        return True
    return refresh_weekly and run.now - last >= REFRESH_AFTER


def _note_credit(run: RefreshRun, rows_written: int) -> int:
    if rows_written and MONEYPUCK_CREDIT not in run.credits:
        run.credits.append(MONEYPUCK_CREDIT)
    return rows_written


def moneypuck(run: RefreshRun) -> None:
    """Read the team file and each goalie file that is missing or, for the team file and the
    current season, older than a week. A finished season is read once."""
    current = current_season_start(run.now)
    if _stale(run, TEAM_GAMES_URL, refresh_weekly=True):
        run.attempt(
            MONEYPUCK,
            TEAM_GAMES_URL,
            lambda stamp: _note_credit(
                run, write_team_games(run.conn, fetch_team_games(run.client), stamp)
            ),
        )
    failures = 0
    for season in range(FIRST_SEASON, current + 1):
        url = goalie_games_url(season)
        if failures >= MAX_UNIT_FAILURES or not _stale(run, url, refresh_weekly=season == current):
            continue

        def unit(stamp: datetime, season: int = season) -> int:
            rows = fetch_goalie_games(run.client, season)
            return _note_credit(run, write_goalie_games(run.conn, rows, stamp))

        failures = 0 if run.attempt(MONEYPUCK, url, unit) else failures + 1


def _write_starters(run: RefreshRun, source: str, reads: list[StarterRead], stamp: datetime) -> int:
    result = write_starter_reads(run.conn, reads, stamp)
    if result.unmatched:
        shown = ", ".join(result.unmatched[:_UNMATCHED_SHOWN])
        run.notes.append(
            f"{source}: {len(result.unmatched)} goalie reads matched no stored game ({shown})"
        )
    return result.written


def espn_starters(run: RefreshRun) -> None:
    """Read the ESPN probable goalies for today and tomorrow, in UTC."""
    today = run.now.date()
    days: list[date] = [today, today + timedelta(days=1)]

    def unit(stamp: datetime) -> int:
        reads = [read for day in days for read in fetch_scoreboard_starters(run.client, day)]
        return _write_starters(run, ESPN_STARTERS, reads, stamp)

    run.attempt(ESPN_STARTERS, f"{ESPN_BASE}/scoreboard", unit)


def espn_injuries(run: RefreshRun) -> None:
    """Read the current ESPN injury list."""
    run.attempt(
        ESPN_INJURIES,
        f"{ESPN_BASE}/injuries",
        lambda stamp: write_injury_reads(run.conn, fetch_injuries(run.client), stamp),
    )


def daily_faceoff(run: RefreshRun) -> None:
    """Read the Daily Faceoff starting goalies."""
    run.attempt(
        DAILY_FACEOFF,
        STARTERS_URL,
        lambda stamp: _write_starters(run, DAILY_FACEOFF, fetch_starters(run.client), stamp),
    )
