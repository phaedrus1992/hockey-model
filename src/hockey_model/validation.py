"""Checks on what a plugin model returns, shared by every public entry point.

A plugin is outside code. Its result is checked before the library returns it, and an
invalid result is never clamped. This module imports only ``types``, so any module can use it.
"""

import math
from enum import StrEnum
from typing import TypeGuard

from hockey_model.types import ProbabilityError, Projection, ProjectionError

# How far a returned level may differ from the requested level, for float rounding only.
LEVEL_TOLERANCE = 1e-9


class Domain(StrEnum):
    """The values a stat can take."""

    PROBABILITY = "probability"  # fractions: every value from 0 to 1
    NONNEGATIVE = "nonnegative"  # counts and goals-against average: no value below 0


# A rate such as goals-against average can exceed one, so only the fractions are bounded above.
_PROBABILITY_STATS = frozenset({"save_pct", "shooting_pct"})
_NONNEGATIVE_STATS = frozenset(
    {
        "goals",
        "assists",
        "points",
        "shots",
        "hits",
        "blocks",
        "wins",
        "saves",
        "shutouts",
        "goals_against_average",
        "gaa",
    }
)


def stat_domain(stat: str) -> Domain | None:
    """Return the domain of a stat, or ``None``: an extension stat has none until it is listed.

    A stat with no domain gets the shape checks only.
    """
    if stat in _PROBABILITY_STATS:
        return Domain.PROBABILITY
    if stat in _NONNEGATIVE_STATS:
        return Domain.NONNEGATIVE
    return None


def _is_number(value: object) -> TypeGuard[int | float]:
    """Return True for an int or float. A bool is not a number here."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_probability(value: object, operation: str, label: str) -> None:
    """Raise ``ProbabilityError`` unless ``value`` is a finite number from 0 to 1."""
    if not _is_number(value) or not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ProbabilityError(
            f"{operation}: invalid {label} {value!r}; return a finite number from 0 to 1"
        )


def validate_projection(
    value: object, requested_level: float, operation: str, domain: Domain | None
) -> Projection:
    """Return ``value`` when it is a valid projection at the requested level, else raise.

    ``ProjectionError`` names a structural fault. ``ProbabilityError`` names a value outside
    0 to 1 in the probability domain.
    """
    if not isinstance(value, Projection):
        raise ProjectionError(
            f"{operation}: the model returned {type(value).__name__}, expected a Projection; "
            "return a Projection"
        )
    for name in ("point", "low", "high", "level"):
        field = getattr(value, name)
        if not _is_number(field) or not math.isfinite(field):
            raise ProjectionError(
                f"{operation}: projection {name} is {field!r}; return a finite number"
            )
    _check_domain(value, operation, domain)
    if not value.low <= value.point <= value.high:
        raise ProjectionError(
            f"{operation}: point {value.point} is outside the interval "
            f"{value.low} to {value.high}; return low <= point <= high"
        )
    if not math.isclose(value.level, requested_level, rel_tol=0.0, abs_tol=LEVEL_TOLERANCE):
        raise ProjectionError(
            f"{operation}: the projection has level {value.level} but {requested_level} "
            "was requested; return the requested level"
        )
    return value


def _check_domain(value: Projection, operation: str, domain: Domain | None) -> None:
    """Raise unless the point and both bounds are inside the domain."""
    bounds = (value.point, value.low, value.high)
    if domain is Domain.PROBABILITY and any(not 0.0 <= v <= 1.0 for v in bounds):
        raise ProbabilityError(
            f"{operation}: invalid probability projection {value!r}; "
            "return point and interval bounds in [0, 1]"
        )
    if domain is Domain.NONNEGATIVE and any(v < 0.0 for v in bounds):
        raise ProjectionError(
            f"{operation}: the projection has a value below zero ({value!r}); "
            "this stat cannot be negative"
        )
