"""Save and load fitted models."""

import json
import sqlite3
from datetime import datetime

from hockey_model.game_model.logistic import LogisticFit
from hockey_model.store.db import StoreError
from hockey_model.store.timestamps import iso_utc


def save_fit(
    conn: sqlite3.Connection, fit: LogisticFit, fit_through_season: int, created_at: datetime
) -> int:
    """Store a fit and return its id."""
    weights = {
        "intercept": fit.intercept,
        "elo_weight": fit.elo_weight,
        "features": dict(fit.weights),
    }
    with conn:
        cursor = conn.execute(
            "INSERT INTO model_fits (fit_through_season, features, weights, created_at)"
            " VALUES (?,?,?,?)",
            (
                fit_through_season,
                json.dumps(list(fit.features)),
                json.dumps(weights, sort_keys=True),
                iso_utc(created_at),
            ),
        )
    if cursor.lastrowid is None:
        raise StoreError("save the model fit: the database gave no row id; check the store")
    return cursor.lastrowid


def newest_fit(conn: sqlite3.Connection) -> LogisticFit:
    """Return the fit that was saved last, or raise when there is none."""
    row = conn.execute(
        "SELECT features, weights FROM model_fits ORDER BY created_at DESC, fit_id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        raise StoreError("load the model fit: none is saved; run `hockey-model fit` first")
    try:
        features = tuple(json.loads(row[0]))
        stored = json.loads(row[1])
        return LogisticFit(
            features,
            float(stored["intercept"]),
            float(stored["elo_weight"]),
            {name: float(value) for name, value in stored["features"].items()},
        )
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise StoreError(
            f"load the model fit: the saved fit is malformed ({type(exc).__name__}: {exc}); "
            "run `hockey-model fit` again"
        ) from exc
