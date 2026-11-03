"""Tests for the training rows."""

import math
import sqlite3

import pytest
from seeding import add_game, utc

from hockey_model.game_model.elo import EloBook, replay
from hockey_model.game_model.features import GoalieMode
from hockey_model.game_model.training import game_input, training_rows
from hockey_model.store.reads import final_games_before


def logit(p: float) -> float:
    return math.log(p / (1 - p))


def seed(store: sqlite3.Connection, last_score: tuple[int, int] = (3, 2)) -> None:
    add_game(store, 1, "2014-11-01T00:00", season=20142015)
    add_game(store, 2, "2015-11-01T00:00", season=20152016, score=(1, 4))
    add_game(store, 3, "2015-11-03T00:00", season=20152016, home="BOS", away="TOR")
    add_game(store, 4, "2016-11-03T00:00", season=20162017, score=last_score)


def test_rows_cover_the_asked_seasons_only(store: sqlite3.Connection) -> None:
    seed(store)
    rows = training_rows(store, 20152016, 20152016, GoalieMode.ACTUAL)
    assert [r.game.game_id for r in rows] == [2, 3]


def test_rows_before_the_first_season_still_move_the_elo(store: sqlite3.Connection) -> None:
    seed(store)
    first = training_rows(store, 20152016, 20152016, GoalieMode.ACTUAL)[0]
    burn_in = replay(
        g for g in final_games_before(store, utc("2020-01-01T00:00")) if g.game_id == 1
    )
    assert first.features.elo_logit == pytest.approx(logit(burn_in.home_win_chance("TOR", "BOS")))


def test_the_first_row_uses_the_initial_ratings_without_burn_in(store: sqlite3.Connection) -> None:
    add_game(store, 2, "2015-11-01T00:00", season=20152016)
    row = training_rows(store, 20152016, 20152016, GoalieMode.ACTUAL)[0]
    assert row.features.elo_logit == pytest.approx(logit(EloBook().home_win_chance("TOR", "BOS")))


def test_the_home_result_is_the_label(store: sqlite3.Connection) -> None:
    seed(store)
    rows = training_rows(store, 20152016, 20152016, GoalieMode.ACTUAL)
    assert [r.home_won for r in rows] == [False, True]


def test_a_row_does_not_see_its_own_result(store: sqlite3.Connection) -> None:
    seed(store, last_score=(5, 0))
    first = training_rows(store, 20162017, 20162017, GoalieMode.ACTUAL)[0]
    store.execute("UPDATE games SET home_score = 0, away_score = 5 WHERE game_id = 4")
    second = training_rows(store, 20162017, 20162017, GoalieMode.ACTUAL)[0]
    assert first.features.elo_logit == second.features.elo_logit
    assert first.home_won != second.home_won


def test_a_later_result_moves_the_next_row(store: sqlite3.Connection) -> None:
    seed(store)
    before = training_rows(store, 20162017, 20162017, GoalieMode.ACTUAL)[0]
    store.execute("UPDATE games SET home_score = 0, away_score = 9 WHERE game_id = 2")
    after = training_rows(store, 20162017, 20162017, GoalieMode.ACTUAL)[0]
    assert before.features.elo_logit != after.features.elo_logit


def test_game_input_copies_the_stored_game(store: sqlite3.Connection) -> None:
    seed(store)
    row = training_rows(store, 20152016, 20152016, GoalieMode.ACTUAL)[0]
    game = game_input(row.game)
    assert (game.game_id, game.home, game.away, game.start) == (2, "TOR", "BOS", row.game.start)
