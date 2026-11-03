"""A small L2-regularized logistic regression, fitted by Newton-Raphson (IRLS).

It uses the standard library only. The matrices have at most a few columns, so plain
lists are enough.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from hockey_model.game_model.features import FeatureRow

L2 = 1.0
MAX_ITERATIONS = 50
TOLERANCE = 1e-9
_WEIGHT_CAP = 30.0
# A tiny ridge on the intercept keeps the system solvable when every game has one result.
_INTERCEPT_RIDGE = 1e-6


@dataclass(frozen=True, slots=True)
class LogisticFit:
    """Weights for ``intercept + elo_weight * elo_logit + sum(weights[f] * value[f])``."""

    features: tuple[str, ...]
    intercept: float
    elo_weight: float
    weights: Mapping[str, float]


ELO_ONLY = LogisticFit(features=(), intercept=0.0, elo_weight=1.0, weights={})


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    exp = math.exp(z)
    return exp / (1.0 + exp)


def _solve(matrix: list[list[float]], vector: list[float]) -> list[float]:
    """Solve ``matrix @ x = vector`` by Gaussian elimination with partial pivoting."""
    size = len(vector)
    rows = [[*matrix[i], vector[i]] for i in range(size)]
    for col in range(size):
        pivot = max(range(col, size), key=lambda r: abs(rows[r][col]))
        if abs(rows[pivot][col]) < 1e-12:  # noqa: PLR2004  # the L2 term keeps this positive
            raise ValueError("fit logistic: the normal equations are singular")
        rows[col], rows[pivot] = rows[pivot], rows[col]
        for r in range(col + 1, size):
            factor = rows[r][col] / rows[col][col]
            for c in range(col, size + 1):
                rows[r][c] -= factor * rows[col][c]
    solution = [0.0] * size
    for r in range(size - 1, -1, -1):
        tail = sum(rows[r][c] * solution[c] for c in range(r + 1, size))
        solution[r] = (rows[r][size] - tail) / rows[r][r]
    return solution


def _design(rows: Sequence[FeatureRow], features: Sequence[str]) -> list[list[float]]:
    return [[row.elo_logit, *(row.values[f] for f in features)] for row in rows]


def _standardize(
    data: list[list[float]],
) -> tuple[list[list[float]], list[float], list[float]]:
    count = len(data)
    columns = len(data[0])
    means = [sum(row[c] for row in data) / count for c in range(columns)]
    scales = []
    for c in range(columns):
        variance = sum((row[c] - means[c]) ** 2 for row in data) / count
        scales.append(math.sqrt(variance) if variance > 0 else 1.0)
    scaled = [[(row[c] - means[c]) / scales[c] for c in range(columns)] for row in data]
    return scaled, means, scales


def _newton_step(data: list[list[float]], wins: Sequence[bool], beta: list[float]) -> list[float]:
    size = len(beta)
    gradient = [L2 * beta[j] if j else _INTERCEPT_RIDGE * beta[0] for j in range(size)]
    hessian = [
        [(L2 if i else _INTERCEPT_RIDGE) if i == j else 0.0 for j in range(size)]
        for i in range(size)
    ]
    for row, win in zip(data, wins, strict=True):
        x = [1.0, *row]
        p = _sigmoid(sum(b * v for b, v in zip(beta, x, strict=True)))
        weight = p * (1.0 - p)
        for i in range(size):
            gradient[i] += (p - (1.0 if win else 0.0)) * x[i]
            for j in range(size):
                hessian[i][j] += weight * x[i] * x[j]
    step = _solve(hessian, gradient)
    return [max(-_WEIGHT_CAP, min(_WEIGHT_CAP, b - s)) for b, s in zip(beta, step, strict=True)]


def fit_logistic(
    rows: Sequence[FeatureRow], wins: Sequence[bool], features: Sequence[str]
) -> LogisticFit:
    """Fit the home win on the Elo logit and ``features``.

    Features are scaled to unit variance inside the fit, so ``L2`` treats them alike.
    The returned weights are on the original scale.
    """
    if not rows:
        raise ValueError("fit logistic: no rows; build the feature rows first")
    if len(rows) != len(wins):
        raise ValueError(f"fit logistic: {len(rows)} rows but {len(wins)} results; pass one each")
    data, means, scales = _standardize(_design(rows, features))
    beta = [0.0] * (len(data[0]) + 1)
    for _ in range(MAX_ITERATIONS):
        updated = _newton_step(data, wins, beta)
        done = max(abs(a - b) for a, b in zip(updated, beta, strict=True)) < TOLERANCE
        beta = updated
        if done:
            break
    else:
        raise ValueError(
            f"fit logistic: no convergence in {MAX_ITERATIONS} iterations; check the feature rows"
        )
    raw = [beta[c + 1] / scales[c] for c in range(len(scales))]
    intercept = beta[0] - sum(raw[c] * means[c] for c in range(len(scales)))
    return LogisticFit(
        tuple(features), intercept, raw[0], dict(zip(features, raw[1:], strict=True))
    )


def predict_logistic(fit: LogisticFit, row: FeatureRow) -> float:
    """Return the home win chance for one feature row."""
    z = fit.intercept + fit.elo_weight * row.elo_logit
    z += sum(fit.weights[f] * row.values[f] for f in fit.features)
    return _sigmoid(z)
