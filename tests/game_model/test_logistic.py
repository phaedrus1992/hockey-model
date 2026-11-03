"""Tests for the logistic fit."""

import math
import random

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from hockey_model.game_model.features import FeatureRow
from hockey_model.game_model.logistic import (
    ELO_ONLY,
    GRADIENT_TOLERANCE,
    LogisticFit,
    fit_logistic,
    predict_logistic,
    solve_linear,
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


@settings(max_examples=25, deadline=None)
@given(st.integers(min_value=0, max_value=10_000))
def test_fit_is_finite_and_ignores_row_order(seed: int) -> None:
    rows, wins = sample(300, seed)
    fit = fit_logistic(rows, wins, ["xg_form"])
    order = list(range(len(rows)))
    random.Random(seed).shuffle(order)
    shuffled = fit_logistic([rows[i] for i in order], [wins[i] for i in order], ["xg_form"])
    assert math.isfinite(fit.intercept) and math.isfinite(fit.elo_weight)
    assert fit.diagnostics is not None
    assert fit.diagnostics.gradient_norm < GRADIENT_TOLERANCE
    assert shuffled.intercept == pytest.approx(fit.intercept, abs=1e-6)
    assert shuffled.weights["xg_form"] == pytest.approx(fit.weights["xg_form"], abs=1e-6)
    assert all(0.0 < predict_logistic(fit, r) < 1.0 for r in rows)


def _objective(
    fit: LogisticFit, rows: list[FeatureRow], wins: list[bool], beta: list[float]
) -> float:
    """Penalized log loss in scaled space, written apart from the code under test."""
    assert fit.diagnostics is not None
    names = ["elo_logit", *fit.features]
    total = 0.5 * 1e-6 * beta[0] ** 2 + 0.5 * fit.diagnostics.l2 * sum(b * b for b in beta[1:])
    for r, win in zip(rows, wins, strict=True):
        raw = [r.elo_logit, *(r.values[f] for f in fit.features)]
        z = beta[0] + sum(
            b * (v - fit.diagnostics.means[n]) / fit.diagnostics.scales[n]
            for b, v, n in zip(beta[1:], raw, names, strict=True)
        )
        total += math.log1p(math.exp(z)) - (z if win else 0.0)
    return total


def _scaled_beta(fit: LogisticFit) -> list[float]:
    assert fit.diagnostics is not None
    names = ["elo_logit", *fit.features]
    raw = [fit.elo_weight, *(fit.weights[f] for f in fit.features)]
    return [
        fit.intercept + sum(w * fit.diagnostics.means[n] for w, n in zip(raw, names, strict=True))
    ] + [w * fit.diagnostics.scales[n] for w, n in zip(raw, names, strict=True)]


def test_fit_certifies_itself() -> None:
    rows, wins = sample(1000)
    fit = fit_logistic(rows, wins, ["xg_form"])
    diag = fit.diagnostics
    assert diag is not None
    assert 1 <= diag.iterations <= 50
    assert diag.gradient_norm < 1e-6
    assert diag.l2 == 1.0
    assert set(diag.means) == set(diag.scales) == {"elo_logit", "xg_form"}
    assert diag.stop_reason.startswith("converged")
    assert math.isfinite(diag.objective) and math.isfinite(diag.condition)


@pytest.mark.parametrize("features", [["xg_form"], ["xg_form", "rest"], []])
def test_fit_is_a_minimum_of_the_penalized_loss(features: list[str]) -> None:
    rows, wins = sample(400, seed=3)
    fit = fit_logistic(rows, wins, features)
    beta = _scaled_beta(fit)
    best = _objective(fit, rows, wins, beta)
    assert best == pytest.approx(fit.diagnostics.objective, rel=1e-9)  # ty: ignore[unresolved-attribute]
    for j in range(len(beta)):
        for delta in (-1e-3, 1e-3):
            moved = [b + (delta if k == j else 0.0) for k, b in enumerate(beta)]
            assert _objective(fit, rows, wins, moved) >= best


def test_collinear_features_share_the_weight() -> None:
    rows, wins = sample(600, seed=5)
    twins = [row(r.elo_logit, xg_form=r.values["xg_form"], rest=r.values["xg_form"]) for r in rows]
    fit = fit_logistic(twins, wins, ["xg_form", "rest"])
    assert fit.weights["xg_form"] == pytest.approx(fit.weights["rest"], rel=1e-6)
    assert fit.diagnostics is not None
    assert fit.diagnostics.gradient_norm < 1e-6


def test_a_clipped_step_is_not_convergence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("hockey_model.game_model.logistic._WEIGHT_CAP", 0.01)
    rows, wins = sample(500)
    with pytest.raises(ValueError, match=r"no convergence.*gradient"):
        fit_logistic(rows, wins, ["xg_form"])


def test_too_few_iterations_name_the_gradient(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("hockey_model.game_model.logistic.MAX_ITERATIONS", 1)
    rows, wins = sample(500)
    with pytest.raises(ValueError, match="no convergence in 1 iterations"):
        fit_logistic(rows, wins, ["xg_form"])


def test_solve_reports_the_pivot_ratio_as_the_condition() -> None:
    solution, condition = solve_linear([[4.0, 0.0], [0.0, 1.0]], [8.0, 3.0])
    assert solution == pytest.approx([2.0, 3.0])
    assert condition == pytest.approx(4.0)


def test_solve_rejects_a_singular_system() -> None:
    with pytest.raises(ValueError, match="singular"):
        solve_linear([[1.0, 1.0], [1.0, 1.0]], [1.0, 2.0])
