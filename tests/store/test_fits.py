"""Tests for saved fits."""

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from hockey_model.game_model.logistic import FitDiagnostics, LogisticFit
from hockey_model.store.db import StoreError
from hockey_model.store.fits import newest_fit, save_fit

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def test_newest_fit_missing_raises(store: sqlite3.Connection) -> None:
    with pytest.raises(StoreError, match="run `hockey-model fit` first"):
        newest_fit(store)


def test_save_and_load_a_fit(store: sqlite3.Connection) -> None:
    fit = LogisticFit(("xg_form", "rest"), 0.1, 0.9, {"xg_form": 2.5, "rest": -0.05})
    save_fit(store, fit, 20252026, T0)
    assert newest_fit(store) == fit


def test_the_newest_fit_wins(store: sqlite3.Connection) -> None:
    old = LogisticFit((), 0.0, 1.0, {})
    new = LogisticFit(("rest",), 0.2, 1.1, {"rest": 0.01})
    save_fit(store, new, 20252026, T0 + timedelta(days=1))
    save_fit(store, old, 20242025, T0)
    assert newest_fit(store) == new


def test_save_fit_returns_increasing_ids(store: sqlite3.Connection) -> None:
    fit = LogisticFit((), 0.0, 1.0, {})
    assert save_fit(store, fit, 20252026, T0) < save_fit(store, fit, 20252026, T0)


@pytest.mark.parametrize(
    ("features", "weights"),
    [
        ("not json", "{}"),
        ('["rest"]', "{}"),
        ('["rest"]', '{"intercept": 0, "elo_weight": 1}'),
        ('["rest"]', '{"intercept": "x", "elo_weight": 1, "features": {}}'),
    ],
)
def test_a_malformed_saved_fit_says_to_fit_again(
    store: sqlite3.Connection, features: str, weights: str
) -> None:
    store.execute(
        "INSERT INTO model_fits (fit_through_season, features, weights, created_at)"
        " VALUES (1, ?, ?, '2026-01-01T00:00:00.000000+00:00')",
        (features, weights),
    )
    with pytest.raises(StoreError, match="malformed.*run `hockey-model fit` again"):
        newest_fit(store)


DIAGNOSTICS = FitDiagnostics(
    iterations=6,
    objective=9123.5,
    gradient_norm=2e-9,
    condition=4.2e3,
    l2=1.0,
    means={"elo_logit": 0.1, "rest": 0.0},
    scales={"elo_logit": 0.4, "rest": 1.0},
    stop_reason="converged: largest gradient entry below 1e-06",
)

_NO_DIAGNOSTICS = '{"intercept": 0, "elo_weight": 1, "features": {}}'
_BAD_DIAGNOSTICS = (
    '{"intercept": 0, "elo_weight": 1, "features": {}, "diagnostics": {"iterations": 1}}'
)
_INSERT = (
    "INSERT INTO model_fits (fit_through_season, features, weights, created_at)"
    " VALUES (1, '[]', ?, '2026-01-01T00:00:00.000000+00:00')"
)


def test_diagnostics_survive_a_save_and_load(store: sqlite3.Connection) -> None:
    fit = LogisticFit(("rest",), 0.1, 0.9, {"rest": 0.02}, DIAGNOSTICS)
    save_fit(store, fit, 20252026, T0)
    assert newest_fit(store) == fit


def test_a_fit_saved_without_diagnostics_loads_with_none(store: sqlite3.Connection) -> None:
    store.execute(_INSERT, (_NO_DIAGNOSTICS,))
    assert newest_fit(store).diagnostics is None


def test_malformed_diagnostics_say_to_fit_again(store: sqlite3.Connection) -> None:
    store.execute(_INSERT, (_BAD_DIAGNOSTICS,))
    with pytest.raises(StoreError, match="malformed.*run `hockey-model fit` again"):
        newest_fit(store)


_FINITE = st.floats(allow_nan=False, allow_infinity=False)


@settings(max_examples=40, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    iterations=st.integers(min_value=0, max_value=50),
    numbers=st.lists(_FINITE, min_size=4, max_size=4),
    scaling=st.dictionaries(st.text(min_size=1, max_size=8), _FINITE, max_size=3),
)
def test_any_diagnostics_round_trip_through_the_store(
    store: sqlite3.Connection, iterations: int, numbers: list[float], scaling: dict[str, float]
) -> None:
    objective, gradient_norm, condition, l2 = numbers
    diagnostics = FitDiagnostics(
        iterations, objective, gradient_norm, condition, l2, scaling, dict(scaling), "stop"
    )
    fit = LogisticFit((), 0.0, 1.0, {}, diagnostics)
    save_fit(store, fit, 20252026, T0)
    assert newest_fit(store) == fit
