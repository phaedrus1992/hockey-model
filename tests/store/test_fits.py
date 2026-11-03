"""Tests for saved fits."""

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from hockey_model.game_model.logistic import LogisticFit
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
