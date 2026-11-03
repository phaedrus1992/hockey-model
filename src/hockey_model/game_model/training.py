"""Build the feature rows of past games, in start order, with the Elo before each game."""

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from hockey_model.game import Game
from hockey_model.game_model.elo import EloBook
from hockey_model.game_model.features import FeatureRow, GoalieMode, build_features
from hockey_model.game_model.seasons import ELO_BURN_IN
from hockey_model.sources.nhl import GameRow
from hockey_model.store.reads import final_games_before, player_catalog

# Later than any game, so every final game in the store is read.
_END_OF_TIME = datetime(9000, 1, 1, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class TrainingRow:
    """A past game, its features as known at the start, and the home result."""

    game: GameRow
    features: FeatureRow
    home_won: bool


def game_input(row: GameRow) -> Game:
    """Return the public ``Game`` for a stored game."""
    return Game(row.game_id, row.home, row.away, row.start)


def training_rows(
    conn: sqlite3.Connection, first_season: int, last_season: int, mode: GoalieMode
) -> list[TrainingRow]:
    """Return a row for each final game from ``first_season`` through ``last_season``.

    The Elo replays from ``ELO_BURN_IN``. Each row uses the ratings before its own game
    and no data from after its start.
    """
    games = [g for g in final_games_before(conn, _END_OF_TIME) if g.season >= ELO_BURN_IN]
    catalog = player_catalog(conn)
    book = EloBook()
    rows: list[TrainingRow] = []
    for game in games:
        if game.season > last_season:
            break
        if game.season >= first_season:
            features = build_features(
                conn, game_input(game), game.start, book, goalie_mode=mode, catalog=catalog
            )
            rows.append(
                TrainingRow(game, features, (game.home_score or 0) > (game.away_score or 0))
            )
        book.update(game)
    return rows
