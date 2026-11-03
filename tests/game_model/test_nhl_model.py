"""Tests for the NHL game model."""

import math
import sqlite3
import urllib.request
from datetime import timedelta

import pytest
from seeding import FETCHED, add_game, add_goalie, add_goalie_form, add_team_form, utc

from hockey_model.game import Game, MissingKind, game_win_probability
from hockey_model.game_model.features import GoalieMode
from hockey_model.game_model.logistic import ELO_ONLY, LogisticFit
from hockey_model.game_model.nhl_model import LEAGUE_GOALS, NhlGameModel
from hockey_model.sources.moneypuck import MONEYPUCK_CREDIT
from hockey_model.store.source_reads import record_read

START = utc("2026-01-20T00:00")
AS_OF = utc("2026-01-19T16:00")
GAME = Game(100, "TOR", "BOS", START)


def model(store: sqlite3.Connection, fit: LogisticFit = ELO_ONLY) -> NhlGameModel:
    return NhlGameModel(store, fit, GoalieMode.GUESS)


def season(store: sqlite3.Connection) -> None:
    for day in (15, 16, 17):
        add_game(store, day, f"2026-01-{day}T00:00", home="TOR", away="MTL")
        add_game(store, day + 100, f"2026-01-{day}T00:00", home="MTL", away="BOS")
        add_team_form(store, day, "TOR", 3.5, 2.0)
        add_team_form(store, day + 100, "BOS", 2.0, 3.0)


def test_nhl_model_sums_to_one(store: sqlite3.Connection) -> None:
    season(store)
    result = model(store).predict(GAME, AS_OF, 0.8)
    assert result.home_win + result.away_win == pytest.approx(1.0, abs=1e-12)
    assert 0.0 < result.home_win < 1.0


def test_with_no_history_the_elo_only_model_favors_home_a_little(store: sqlite3.Connection) -> None:
    result = model(store).predict(GAME, AS_OF, 0.8)
    assert result.home_win == pytest.approx(1 / (1 + 10 ** (-28 / 400)), abs=1e-12)


def test_the_fit_weights_change_the_result(store: sqlite3.Connection) -> None:
    season(store)
    plain = model(store).predict(GAME, AS_OF, 0.8).home_win
    boosted = LogisticFit(("xg_form",), 0.0, 1.0, {"xg_form": 4.0})
    assert model(store, boosted).predict(GAME, AS_OF, 0.8).home_win > plain


def test_nhl_model_credits_moneypuck(store: sqlite3.Connection) -> None:
    season(store)
    assert model(store).predict(GAME, AS_OF, 0.8).credits == (MONEYPUCK_CREDIT,)


def test_no_credit_without_moneypuck_rows(store: sqlite3.Connection) -> None:
    add_game(store, 1, "2026-01-15T00:00")
    assert model(store).predict(GAME, AS_OF, 0.8).credits == ()


def test_nhl_model_reports_stale_source(store: sqlite3.Connection) -> None:
    season(store)
    record_read(store, "espn_starters", "u", utc("2026-01-19T10:00"))
    record_read(store, "espn_starters", "u", utc("2026-01-19T12:00"), error="HTTP 503")
    record_read(store, "daily_faceoff", "u", utc("2026-01-19T12:00"))
    result = model(store).predict(GAME, AS_OF, 0.8)
    stale = [m for m in result.missing if m.kind is MissingKind.STALE_SOURCE]
    assert len(stale) == 1
    assert "espn_starters" in stale[0].note


def test_a_later_good_read_clears_the_stale_flag(store: sqlite3.Connection) -> None:
    record_read(store, "espn_starters", "u", utc("2026-01-19T12:00"), error="HTTP 503")
    record_read(store, "espn_starters", "u", utc("2026-01-19T13:00"))
    result = model(store).predict(GAME, AS_OF, 0.8)
    assert MissingKind.STALE_SOURCE not in [m.kind for m in result.missing]


def test_nhl_model_makes_no_network_call(
    store: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    season(store)

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("the model made a network request")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    assert model(store).predict(GAME, AS_OF, 0.8).home_win > 0


def test_expected_goals_use_moneypuck_attack_and_defence(store: sqlite3.Connection) -> None:
    season(store)
    result = model(store).predict(GAME, AS_OF, 0.8)
    assert result.home_goals.point == pytest.approx((3.5 + 3.0) / 2)
    assert result.away_goals.point == pytest.approx((2.0 + 2.0) / 2)


def test_expected_goals_fall_back_to_actual_goals(store: sqlite3.Connection) -> None:
    add_game(store, 1, "2026-01-15T00:00", home="TOR", away="MTL")
    add_game(store, 2, "2026-01-16T00:00", home="MTL", away="BOS")
    result = model(store).predict(GAME, AS_OF, 0.8)
    assert result.home_goals.point == pytest.approx((3 + 3) / 2)
    assert result.away_goals.point == pytest.approx((2 + 2) / 2)


def test_expected_goals_without_any_game_use_the_league_average(store: sqlite3.Connection) -> None:
    result = model(store).predict(GAME, AS_OF, 0.8)
    assert result.home_goals.point == LEAGUE_GOALS
    assert [m.kind for m in result.missing].count(MissingKind.XG_FORM) >= 2


def test_goal_interval_is_poisson_and_contains_the_point(store: sqlite3.Connection) -> None:
    season(store)
    wide = model(store).predict(GAME, AS_OF, 0.95).home_goals
    narrow = model(store).predict(GAME, AS_OF, 0.5).home_goals
    assert wide.low <= narrow.low <= narrow.point <= narrow.high <= wide.high
    assert wide.high - wide.low > narrow.high - narrow.low
    assert wide.level == 0.95


def test_goal_interval_matches_poisson_quantiles(store: sqlite3.Connection) -> None:
    season(store)
    projection = model(store).predict(GAME, AS_OF, 0.8).home_goals
    rate = projection.point
    cdf = 0.0
    low, high = 0, 0
    found_low = found_high = False
    for k in range(40):
        cdf += math.exp(-rate) * rate**k / math.factorial(k)
        if not found_low and cdf >= 0.1:
            low, found_low = k, True
        if not found_high and cdf >= 0.9:
            high, found_high = k, True
    assert (projection.low, projection.high) == (min(low, rate), max(high, rate))


def test_a_goalie_feature_uses_the_guessed_starter(store: sqlite3.Connection) -> None:
    season(store)
    for day in (15, 16, 17):
        add_goalie(store, day, "TOR", 11, "C. Ingram")
        add_goalie_form(store, day, 11, 3.0, 0)
    fit = LogisticFit(("goalie_gsax",), 0.0, 1.0, {"goalie_gsax": 1.0})
    with_goalie = model(store, fit).predict(GAME, AS_OF, 0.8)
    without = model(store).predict(GAME, AS_OF, 0.8)
    assert with_goalie.home_win > without.home_win


def test_game_win_probability_flags_a_late_prediction(store: sqlite3.Connection) -> None:
    season(store)
    late = START + timedelta(hours=1)
    result = game_win_probability(GAME, model(store), as_of=late)
    assert result.made_after_start
    assert MissingKind.LATE_RUN in [m.kind for m in result.missing]
    on_time = game_win_probability(GAME, model(store), as_of=AS_OF)
    assert not on_time.made_after_start


def test_a_late_prediction_does_not_use_the_game_result(store: sqlite3.Connection) -> None:
    season(store)
    pregame = model(store).predict(GAME, AS_OF, 0.8)
    add_game(store, 100, "2026-01-20T00:00", fetched_at=FETCHED)
    late = model(store).predict(GAME, START + timedelta(hours=6), 0.8)
    assert late.home_win == pytest.approx(pregame.home_win)
