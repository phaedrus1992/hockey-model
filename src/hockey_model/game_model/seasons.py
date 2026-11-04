"""The seasons that the fit and the backtest use. A season is written as the NHL writes it."""

from dataclasses import dataclass

# The Elo replays from this season. Its games set the ratings and are never in a fit.
ELO_BURN_IN = 20142015
# The first season in a fit.
FIT_FIRST = 20152016
# Features are chosen on these seasons only. The fit uses the first range, and the
# second range is the validation that can veto a feature.
SELECT_TRAIN = (20152016, 20212022)
SELECT_VALIDATE = (20222023, 20232024)
# The seasons that are scored, once each.
SCORED = (20242025, 20252026)

# Experiment cohorts.
# EXPLORATION covers every season through 2025-26. Results from these seasons
# are labeled exploratory and never promote a feature.
EXPLORATION = (FIT_FIRST, 20252026)
# CONFIRMATION covers the 2026-27 regular season and any later season.
# Regular season only: game types 2 (regular) and 3 (playoffs) are included.
# The owner later approved regular-season scope only for the confirmation cohort.
CONFIRMATION_START = 20262027


@dataclass(frozen=True, slots=True)
class SeasonPlan:
    """The season ranges of one backtest. A test passes a short plan."""

    burn_in: int = ELO_BURN_IN
    fit_first: int = FIT_FIRST
    select_train: tuple[int, int] = SELECT_TRAIN
    select_validate: tuple[int, int] = SELECT_VALIDATE
    scored: tuple[int, int] = SCORED
    # Confirmation cohort: scored from this season onward (regular season only).
    # When None, the plan uses the standard scored range.
    confirmation_start: int | None = None


def _confirmation_plan(confirmation_start: int = CONFIRMATION_START) -> SeasonPlan:
    """Return a SeasonPlan for a confirmation test.

    The confirmation test scores every season from the confirmation start
    onward. Regular season games only: game types 2 and 3.
    """
    return SeasonPlan(
        confirmation_start=confirmation_start,
    )


DEFAULT_PLAN = SeasonPlan()
