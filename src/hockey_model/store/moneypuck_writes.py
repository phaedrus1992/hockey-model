"""Write MoneyPuck reads to the store.

A read adds a row only when the game is new or MoneyPuck changed a value, so a weekly
read of the whole file does not copy every row again. Data from MoneyPuck.com.
"""

import sqlite3
from collections.abc import Sequence
from datetime import datetime

from hockey_model.sources.moneypuck import GoalieGameRow, TeamGameRow
from hockey_model.store.source_reads import last_ok_read
from hockey_model.store.timestamps import iso_utc


def write_team_games(
    conn: sqlite3.Connection, rows: Sequence[TeamGameRow], fetched_at: datetime
) -> int:
    """Append the new or changed team-game rows. Return how many were written."""
    newest = {
        (game_id, team): values
        for game_id, team, *values in conn.execute(
            "SELECT t.game_id, t.team, t.game_date, t.xg_for, t.xg_against, t.goals_for,"
            " t.goals_against FROM mp_team_games t JOIN (SELECT game_id, team,"
            " MAX(fetched_at) AS latest FROM mp_team_games GROUP BY game_id, team) n"
            " ON t.game_id = n.game_id AND t.team = n.team AND t.fetched_at = n.latest"
        )
    }
    fresh = [row for row in rows if newest.get((row.game_id, row.team)) != list(row[2:])]
    stamp = iso_utc(fetched_at)
    conn.executemany(
        "INSERT INTO mp_team_games (game_id, team, game_date, xg_for, xg_against, goals_for,"
        " goals_against, fetched_at) VALUES (?,?,?,?,?,?,?,?)",
        [(*row, stamp) for row in fresh],
    )
    return len(fresh)


def write_goalie_games(
    conn: sqlite3.Connection, rows: Sequence[GoalieGameRow], fetched_at: datetime
) -> int:
    """Append the new or changed goalie-game rows. Return how many were written."""
    newest = {
        (game_id, nhl_id): values
        for game_id, nhl_id, *values in conn.execute(
            "SELECT t.game_id, t.nhl_id, t.team, t.xg_against, t.goals_against"
            " FROM mp_goalie_games t JOIN (SELECT game_id, nhl_id, MAX(fetched_at) AS latest"
            " FROM mp_goalie_games GROUP BY game_id, nhl_id) n ON t.game_id = n.game_id"
            " AND t.nhl_id = n.nhl_id AND t.fetched_at = n.latest"
        )
    }
    fresh = [row for row in rows if newest.get((row.game_id, row.nhl_id)) != list(row[2:])]
    stamp = iso_utc(fetched_at)
    conn.executemany(
        "INSERT INTO mp_goalie_games (game_id, nhl_id, team, xg_against, goals_against,"
        " fetched_at) VALUES (?,?,?,?,?,?)",
        [(*row, stamp) for row in fresh],
    )
    return len(fresh)


def last_moneypuck_fetch(conn: sqlite3.Connection, url: str) -> datetime | None:
    """Return the time of the newest good read of ``url``, or ``None`` when there is none."""
    return last_ok_read(conn, "moneypuck", url)
