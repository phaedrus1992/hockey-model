"""Tests for the logistic fit."""

import math
import random

import pytest
from hypothesis import given
from hypothesis import strategies as st

from hockey_model.game_model.features import FeatureRow
from hockey_model.game_model.logistic import (
    ELO_ONLY,
    LogisticFit,
    fit_logistic,
    predict_logistic,
)


def row(elo_logit: float, **values: float) -> FeatureRow:
    full = {"xg_form": 0.0, "goalie_gsax": 0.0, "rest": 0.0, **values}
    return FeatureRow(1, elo_logit, full, (), False)


def sigmoid(z: float) -> float:
    return 1 / (1 + math.exp(-z))


def sample(n: int, seed: int = 0) -> tuple[list[FeatureRow], list[bool]]:
    rng = random.Random(seed)
    rows, wins = [], []
    for _ in range(n):
        elo = rng.gauss(0.1, 0.4)
        xg = rng.gauss(0.0, 0.1)
        rows.append(row(elo, xg_form=xg))
        wins.append(rng.random() < sigmoid(0.1 + 1.0 * elo + 5.0 * xg))
    return rows, wins


def test_fit_logistic_recovers_known_weights() -> None:
    rows, wins = sample(5000)
    fit = fit_logistic(rows, wins, ["xg_form"])
    assert fit.intercept == pytest.approx(0.1, abs=0.1)
    assert fit.elo_weight == pytest.approx(1.0, abs=0.2)
    assert fit.weights["xg_form"] == pytest.approx(5.0, abs=1.0)
    assert fit.features == ("xg_form",)


def test_fit_logistic_is_scale_free() -> None:
    rows, wins = sample(2000)
    scaled = [row(r.elo_logit, xg_form=r.values["xg_form"] * 100) for r in rows]
    base = fit_logistic(rows, wins, ["xg_form"])
    other = fit_logistic(scaled, wins, ["xg_form"])
    assert other.weights["xg_form"] * 100 == pytest.approx(base.weights["xg_form"], rel=0.02)
    assert other.intercept == pytest.approx(base.intercept, abs=0.01)


def test_fit_logistic_elo_only() -> None:
    rows, wins = sample(2000)
    fit = fit_logistic(rows, wins, [])
    assert fit.features == ()
    assert dict(fit.weights) == {}


def test_fit_logistic_rejects_empty() -> None:
    with pytest.raises(ValueError, match="no rows"):
        fit_logistic([], [], [])


def test_fit_logistic_rejects_length_mismatch() -> None:
    with pytest.raises(ValueError, match="2 rows but 1 results"):
        fit_logistic([row(0.0), row(1.0)], [True], [])


def test_fit_logistic_separable_data_stays_finite() -> None:
    rows = [row(x) for x in (-2.0, -1.0, 1.0, 2.0)] * 10
    wins = [x > 0 for x in (-2.0, -1.0, 1.0, 2.0)] * 10
    fit = fit_logistic(rows, wins, [])
    assert math.isfinite(fit.intercept)
    assert math.isfinite(fit.elo_weight)
    assert fit.elo_weight > 0


def test_fit_logistic_constant_feature_gets_no_weight_effect() -> None:
    rows, wins = sample(500)
    fit = fit_logistic(rows, wins, ["rest"])
    assert fit.weights["rest"] == pytest.approx(0.0, abs=1e-9)


def test_fit_logistic_unknown_feature_is_an_error() -> None:
    rows, wins = sample(10)
    with pytest.raises(KeyError):
        fit_logistic(rows, wins, ["nope"])


def test_predict_logistic_matches_the_formula() -> None:
    fit = LogisticFit(("xg_form", "rest"), 0.2, 0.9, {"xg_form": 3.0, "rest": -0.1})
    value = predict_logistic(fit, row(0.5, xg_form=0.2, rest=2.0))
    assert value == pytest.approx(sigmoid(0.2 + 0.9 * 0.5 + 3.0 * 0.2 - 0.1 * 2.0))


def test_elo_only_fit_returns_the_elo_probability() -> None:
    assert predict_logistic(ELO_ONLY, row(0.7)) == pytest.approx(sigmoid(0.7))


def test_predict_logistic_ignores_features_that_were_not_fitted() -> None:
    fit = LogisticFit((), 0.0, 1.0, {})
    assert predict_logistic(fit, row(0.3, xg_form=9.0)) == pytest.approx(sigmoid(0.3))


@given(st.floats(min_value=-50, max_value=50), st.floats(min_value=-50, max_value=50))
def test_predict_logistic_is_a_probability(elo: float, xg: float) -> None:
    fit = LogisticFit(("xg_form",), 1.0, 2.0, {"xg_form": 3.0})
    assert 0.0 <= predict_logistic(fit, row(elo, xg_form=xg)) <= 1.0
