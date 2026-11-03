"""Write NHL score and boxscore reads to the store."""

import sqlite3
from collections.abc import Sequence
from datetime import datetime

from hockey_model.sources.nhl import BoxscoreRows, GameRow
from hockey_model.store.timestamps import iso_utc


def write_games(conn: sqlite3.Connection, rows: Sequence[GameRow], fetched_at: datetime) -> int:
    """Append one read of each game. An earlier read of the same game stays."""
    stamp = iso_utc(fetched_at)
    conn.executemany(
        "INSERT INTO games (game_id, season, game_type, start_utc, home, away, state,"
        " home_score, away_score, last_period, fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                row.game_id,
                row.season,
                row.game_type,
                iso_utc(row.start),
                row.home,
                row.away,
                row.state,
                row.home_score,
                row.away_score,
                row.last_period,
                stamp,
            )
            for row in rows
        ],
    )
    return len(rows)


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


def games_missing_boxscore(conn: sqlite3.Connection) -> list[int]:
    """Return the ids of final games that have no goalie rows yet, oldest first."""
    cursor = conn.execute(
        "SELECT DISTINCT g.game_id FROM games g"
        " WHERE g.state IN ('FINAL', 'OFF')"
        " AND NOT EXISTS (SELECT 1 FROM goalie_games w WHERE w.game_id = g.game_id)"
        " ORDER BY g.start_utc, g.game_id"
    )
    return [row[0] for row in cursor]
