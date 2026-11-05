"""Write NHL score and boxscore reads to the store."""

import sqlite3
from collections.abc import Sequence
from datetime import date, datetime

from hockey_model.game_day import game_day_window
from hockey_model.sources.nhl import FINAL_STATES, BoxscoreRows, GameRow
from hockey_model.store.timestamps import iso_utc


def _values(row: GameRow) -> tuple[object, ...]:
    return (
        row.season,
        row.game_type,
        iso_utc(row.start),
        row.home,
        row.away,
        row.state,
        row.home_score,
        row.away_score,
        row.last_period,
    )


def _newest_reads(conn: sqlite3.Connection, game_ids: list[int]) -> dict[int, tuple[object, ...]]:
    marks = ",".join("?" for _ in game_ids)
    cursor = conn.execute(
        "SELECT game_id, season, game_type, start_utc, home, away, state, home_score,"
        f" away_score, last_period FROM latest_games WHERE game_id IN ({marks})",
        game_ids,
    )
    return {game_id: tuple(rest) for game_id, *rest in cursor}


def write_games(conn: sqlite3.Connection, rows: Sequence[GameRow], fetched_at: datetime) -> int:
    """Append a read of each game that is new or changed. An earlier read stays."""
    if not rows:
        return 0
    newest = _newest_reads(conn, [row.game_id for row in rows])
    fresh = [row for row in rows if newest.get(row.game_id) != _values(row)]
    stamp = iso_utc(fetched_at)
    conn.executemany(
        "INSERT INTO games (game_id, season, game_type, start_utc, home, away, state,"
        " home_score, away_score, last_period, fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [(row.game_id, *_values(row), stamp) for row in fresh],
    )
    return len(fresh)


def _write_players(conn: sqlite3.Connection, rows: BoxscoreRows, stamp: str) -> None:
    for player in rows.players:
        newest = conn.execute(
            "SELECT full_name, position, team FROM players WHERE nhl_id = ?"
            " ORDER BY fetched_at DESC LIMIT 1",
            (player.nhl_id,),
        ).fetchone()
        if newest != (player.full_name, player.position, player.team):
            conn.execute(
                "INSERT INTO players (nhl_id, full_name, position, team, fetched_at)"
                " VALUES (?,?,?,?,?)",
                (*player, stamp),
            )


def write_boxscore(
    conn: sqlite3.Connection, game_id: int, rows: BoxscoreRows, fetched_at: datetime
) -> None:
    """Store the players and stat lines of one final game, once."""
    stamp = iso_utc(fetched_at)
    _write_players(conn, rows, stamp)
    conn.executemany(
        "INSERT INTO skater_games (game_id, team, nhl_id, toi_seconds, goals, assists,"
        " fetched_at) VALUES (?,?,?,?,?,?,?)",
        [(game_id, *skater, stamp) for skater in rows.skaters],
    )
    conn.executemany(
        "INSERT INTO goalie_games (game_id, team, nhl_id, toi_seconds, started, fetched_at)"
        " VALUES (?,?,?,?,?,?)",
        [(game_id, g.team, g.nhl_id, g.toi_seconds, int(g.started), stamp) for g in rows.goalies],
    )


def games_missing_boxscore(
    conn: sqlite3.Connection, first_day: date | None = None, last_day: date | None = None
) -> list[int]:
    """Return the ids of final games that have no goalie rows yet, oldest first.

    ``first_day`` and ``last_day`` are Eastern game days, both included. Either may be None.
    """
    marks = ",".join("?" for _ in FINAL_STATES)
    low = None if first_day is None else iso_utc(game_day_window(first_day)[0])
    high = None if last_day is None else iso_utc(game_day_window(last_day)[1])
    cursor = conn.execute(
        "SELECT DISTINCT g.game_id FROM games g"
        f" WHERE g.state IN ({marks})"
        " AND NOT EXISTS (SELECT 1 FROM goalie_games w WHERE w.game_id = g.game_id)"
        " AND (? IS NULL OR g.start_utc >= ?) AND (? IS NULL OR g.start_utc < ?)"
        " ORDER BY g.start_utc, g.game_id",
        [*sorted(FINAL_STATES), low, low, high, high],
    )
    return [row[0] for row in cursor]
