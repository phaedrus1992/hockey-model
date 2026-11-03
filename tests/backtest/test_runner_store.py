"""The backtest on a small made-up store: the wiring from the store to the report."""

import sqlite3

import pytest
from seeding import add_game

from hockey_model.backtest.runner import run_backtest
from hockey_model.game_model.features import ATTEMPT_FEATURES
from hockey_model.game_model.seasons import SeasonPlan
from hockey_model.types import HockeyModelError

PLAN = SeasonPlan(
    burn_in=1, fit_first=2, select_train=(2, 4), select_validate=(5, 5), scored=(6, 7)
)


def seed(store: sqlite3.Connection, seasons: range) -> None:
    game_id = 0
    for season in seasons:
        for day in range(1, 21):
            game_id += 1
            score = (3, 2) if (game_id * 7) % 5 < 3 else (1, 2)
            home, away = ("TOR", "BOS") if day % 2 else ("BOS", "TOR")
            add_game(
                store,
                game_id,
                f"20{season + 10:02d}-11-{day:02d}T00:00",
                home=home,
                away=away,
                season=season,
                score=score,
            )


def test_the_report_from_a_small_store(store: sqlite3.Connection) -> None:
    seed(store, range(1, 8))
    report, records = run_backtest(store, PLAN)
    assert report.candidate_features == ("xg_form", "goalie_gsax", "rest")
    assert [r.name for r in report.runs] == ["home_rate", "elo", "model_actual", "model_guess"]
    assert all(r.games == 40 for r in report.runs)
    assert len(records) == 3 * 40
    assert {r.game_id for r in records if r.run == "elo"} == set(range(101, 141))


def test_the_backtest_needs_games_in_the_scored_seasons(store: sqlite3.Connection) -> None:
    seed(store, range(1, 6))
    with pytest.raises(HockeyModelError, match="scored seasons"):
        run_backtest(store, PLAN)


def test_the_backtest_needs_games_in_the_selection_seasons(store: sqlite3.Connection) -> None:
    with pytest.raises(HockeyModelError, match="selection seasons"):
        run_backtest(store, PLAN)


def test_the_attempt_candidates_replace_xg_form(store: sqlite3.Connection) -> None:
    seed(store, range(1, 8))
    report, _ = run_backtest(store, PLAN, candidates=ATTEMPT_FEATURES)
    assert report.candidate_features == ("attempt_form", "goalie_gsax", "rest")
    assert set(report.validation) == {"elo", "elo+attempt_form", "elo+goalie_gsax", "elo+rest"}
    assert "xg_form" not in report.tested_features
