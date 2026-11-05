"""Save and load fitted models."""

import json
import math
import sqlite3
from dataclasses import asdict
from datetime import datetime
from typing import Any

from hockey_model.game_model.features import ALL_FEATURE_NAMES
from hockey_model.game_model.logistic import FitDiagnostics, LogisticFit
from hockey_model.store.db import StoreError
from hockey_model.store.timestamps import iso_utc


def save_fit(
    conn: sqlite3.Connection, fit: LogisticFit, fit_through_season: int, created_at: datetime
) -> int:
    """Store a fit and return its id. An invalid fit raises ``StoreError`` and saves no row."""
    try:
        _check_fit(fit)
    except ValueError as exc:
        raise StoreError(
            f"save the model fit: the fit cannot be used ({exc}); "
            f"the features must be any of {', '.join(ALL_FEATURE_NAMES)}, once each"
        ) from exc
    weights: dict[str, object] = {
        "intercept": fit.intercept,
        "elo_weight": fit.elo_weight,
        "features": dict(fit.weights),
    }
    if fit.diagnostics is not None:
        weights["diagnostics"] = asdict(fit.diagnostics)
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
        fit = LogisticFit(
            features,
            float(stored["intercept"]),
            float(stored["elo_weight"]),
            {name: float(value) for name, value in stored["features"].items()},
            _diagnostics(stored.get("diagnostics")),
        )
        _check_fit(fit)
        return fit
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise StoreError(
            f"load the model fit: the saved fit is malformed ({type(exc).__name__}: {exc}); "
            "run `hockey-model fit` again"
        ) from exc


def _check_fit(fit: LogisticFit) -> None:
    """Raise ``ValueError`` for a fit that the model cannot predict with."""
    unknown = [name for name in fit.features if name not in ALL_FEATURE_NAMES]
    if unknown:
        raise ValueError(f"unknown feature {unknown[0]!r}")
    if len(set(fit.features)) != len(fit.features):
        raise ValueError("a feature is named twice")
    if set(fit.weights) != set(fit.features):
        raise ValueError("the features and the weights name different features")
    numbers = [fit.intercept, fit.elo_weight, *fit.weights.values()]
    if not all(math.isfinite(number) for number in numbers):
        raise ValueError("a weight is not a finite number")


def _diagnostics(stored: dict[str, Any] | None) -> FitDiagnostics | None:
    """Rebuild the saved diagnostics. A fit saved before they existed has none."""
    if stored is None:
        return None
    return FitDiagnostics(
        iterations=int(stored["iterations"]),
        objective=float(stored["objective"]),
        gradient_norm=float(stored["gradient_norm"]),
        condition=float(stored["condition"]),
        l2=float(stored["l2"]),
        means={str(k): float(v) for k, v in stored["means"].items()},
        scales={str(k): float(v) for k, v in stored["scales"].items()},
        stop_reason=str(stored["stop_reason"]),
    )
