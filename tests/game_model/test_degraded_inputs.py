"""Tests for the degraded-input field when a team has no MoneyPuck form."""

import math
import sqlite3

import pytest
from seeding import add_game, add_team_form, utc

from hockey_model.game import DegradedInput, Game, MissingKind
from hockey_model.game_model.elo import EloBook
from hockey_model.game_model.features import (
    NEUTRAL_FORM,
    GoalieMode,
    build_features,
)
from hockey_model.game_model.logistic import ELO_ONLY, LogisticFit
from hockey_model.game_model.nhl_model import NhlGameModel

START = utc("2026-01-20T00:00")
AS_OF = utc("2026-01-19T16:00")
HOME, AWAY = "TOR", "BOS"
GAME = Game(100, HOME, AWAY, START)
XG_FIT = LogisticFit(("xg_form",), 0.0, 1.0, {"xg_form": 2.0})


def _form(store: sqlite3.Connection, team: str, xg_for: float, xg_against: float) -> None:
    """One earlier game of ``team`` with MoneyPuck form."""
    number = 10 if team == HOME else 20
    home, away = (team, "MTL") if team == HOME else ("MTL", team)
    add_game(store, number, "2026-01-18T00:00", home=home, away=away)
    add_team_form(store, number, team, xg_for, xg_against)


def _row(store: sqlite3.Connection, names: tuple[str, ...] = ("xg_form",)):
    return build_features(store, GAME, AS_OF, EloBook(), goalie_mode=GoalieMode.GUESS, names=names)


def test_the_neutral_form_is_a_named_zero() -> None:
    assert NEUTRAL_FORM == 0.0


@pytest.mark.parametrize(
    ("with_form", "teams"),
    [((AWAY,), (HOME,)), ((HOME,), (AWAY,)), ((), (HOME, AWAY))],
)
def test_a_team_without_form_makes_the_whole_feature_neutral_and_degraded(
    store: sqlite3.Connection, with_form: tuple[str, ...], teams: tuple[str, ...]
) -> None:
    for team in with_form:
        # A strong one-sided form: it must not leak through as a measured difference.
        _form(store, team, 3.0, 1.0)
    row = _row(store)
    assert row.values["xg_form"] == NEUTRAL_FORM
    assert row.imputed == (DegradedInput("xg_form", MissingKind.XG_FORM, teams),)
    assert [m.team for m in row.missing if m.kind is MissingKind.XG_FORM] == list(teams)


def test_an_equal_measured_form_is_not_degraded(store: sqlite3.Connection) -> None:
    _form(store, HOME, 3.0, 1.0)
    _form(store, AWAY, 3.0, 1.0)
    row = _row(store)
    assert row.values["xg_form"] == 0.0
    assert row.imputed == ()


def test_no_form_feature_means_nothing_is_degraded(store: sqlite3.Connection) -> None:
    assert _row(store, names=("rest",)).imputed == ()


def test_the_attempt_feature_reports_its_own_kind(store: sqlite3.Connection) -> None:
    row = _row(store, names=("attempt_form",))
    assert row.imputed == (DegradedInput("attempt_form", MissingKind.ATTEMPT_FORM, (HOME, AWAY)),)


def test_the_prediction_carries_the_degraded_inputs(store: sqlite3.Connection) -> None:
    _form(store, AWAY, 3.0, 1.0)
    result = NhlGameModel(store, XG_FIT, GoalieMode.GUESS).predict(GAME, AS_OF, 0.8)
    assert result.degraded_inputs == (DegradedInput("xg_form", MissingKind.XG_FORM, (HOME,)),)
    assert math.isfinite(result.home_win)
    assert 0.0 < result.home_win < 1.0
    # The neutral feature adds nothing, so the win chance is the Elo-only chance.
    plain = NhlGameModel(store, ELO_ONLY, GoalieMode.GUESS).predict(GAME, AS_OF, 0.8)
    assert result.home_win == pytest.approx(plain.home_win)


def test_a_fit_without_the_feature_has_no_degraded_win_input(store: sqlite3.Connection) -> None:
    result = NhlGameModel(store, ELO_ONLY, GoalieMode.GUESS).predict(GAME, AS_OF, 0.8)
    assert result.degraded_inputs == ()
    # The goal rates still note the missing form, as before.
    assert any(m.kind is MissingKind.XG_FORM for m in result.missing)
