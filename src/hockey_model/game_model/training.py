"""Build the feature rows of past games, in start order, with the Elo before each game."""

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass

from hockey_model.game import Game
from hockey_model.game_model.elo import EloBook
from hockey_model.game_model.features import FEATURES, FeatureRow, GoalieMode, build_features
from hockey_model.game_model.seasons import ELO_BURN_IN
from hockey_model.sources.nhl import GameRow
from hockey_model.store.reads import LATEST_GAME, final_games_before, player_catalog


@dataclass(frozen=True, slots=True)
class TrainingRow:
    """A past game, its features as known at the start, and the home result."""

    game: GameRow
    features: FeatureRow
    home_won: bool


def game_input(row: GameRow) -> Game:
    """Return the public ``Game`` for a stored game."""
    return Game(row.game_id, row.home, row.away, row.start)


def _home_won(game: GameRow) -> bool:
    if game.home_score is None or game.away_score is None:
        raise ValueError(f"train on game {game.game_id}: a final game has no score; refresh again")
    return game.home_score > game.away_score


def training_rows(
    conn: sqlite3.Connection,
    first_season: int,
    last_season: int,
    mode: GoalieMode,
    burn_in: int = ELO_BURN_IN,
    names: Sequence[str] = FEATURES,
) -> list[TrainingRow]:
    """Return a row for each final game from ``first_season`` through ``last_season``.

    The Elo replays from the ``burn_in`` season. Each row uses the ratings before its own game
    and no data from after its start.
    """
    games = [g for g in final_games_before(conn, LATEST_GAME) if g.season >= burn_in]
    catalog = player_catalog(conn)
    book = EloBook()
    rows: list[TrainingRow] = []
    for game in games:
        if game.season > last_season:
            break
        if game.season >= first_season:
            features = build_features(
                conn,
                game_input(game),
                game.start,
                book,
                goalie_mode=mode,
                catalog=catalog,
                names=names,
            )
            rows.append(TrainingRow(game, features, _home_won(game)))
        book.update(game)
    return rows
