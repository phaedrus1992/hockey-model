"""The imputation quality of a fit is stored with the fit, and only a fit that passed is saved."""

import json
import sqlite3
from datetime import UTC, datetime

import pytest

from hockey_model.game_model.logistic import LogisticFit
from hockey_model.store.fits import save_fit
from hockey_model.types import HockeyModelError

T0 = datetime(2026, 11, 1, tzinfo=UTC)
FIT = LogisticFit(("rest",), 0.0, 1.0, {"rest": 0.5})
QUALITY = [{"feature": "rest", "imputed": 1, "total": 10, "share": 0.1}]


def test_the_quality_is_stored_with_the_fit(store: sqlite3.Connection) -> None:
    fit_id = save_fit(store, FIT, 20252026, T0, imputation=QUALITY)
    (raw,) = store.execute("SELECT weights FROM model_fits WHERE fit_id = ?", (fit_id,)).fetchone()
    assert json.loads(raw)["imputation"] == QUALITY


def test_a_fit_saved_without_quality_stores_no_imputation_key(store: sqlite3.Connection) -> None:
    fit_id = save_fit(store, FIT, 20252026, T0)
    (raw,) = store.execute("SELECT weights FROM model_fits WHERE fit_id = ?", (fit_id,)).fetchone()
    assert "imputation" not in json.loads(raw)


def test_a_fit_with_a_bad_weight_still_saves_nothing(store: sqlite3.Connection) -> None:
    bad = LogisticFit(("rest",), 0.0, 1.0, {"rest": float("nan")})
    with pytest.raises(HockeyModelError):
        save_fit(store, bad, 20252026, T0, imputation=QUALITY)
    assert store.execute("SELECT COUNT(*) FROM model_fits").fetchone()[0] == 0
