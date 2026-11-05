"""The seasons that the fit and the backtest use. A season is written as the NHL writes it."""

from dataclasses import dataclass
from datetime import date, datetime

from hockey_model.sources.nhl import GameRow

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
# EXPLORATION covers every season through 2025-26 that a walk-forward fit can score.
# A scored season needs a fit from an earlier season, so the cohort starts one season
# after FIT_FIRST. Results from these seasons are labeled exploratory and never
# promote a feature. SCORED seasons are inside the range: the backtest report already
# scored them, so an exploration run on them is a repeat look, not a fresh one.
EXPLORATION = (20162017, 20252026)
# CONFIRMATION starts with the 2026-27 season. The owner approved the regular season
# only, so playoff games (NHL game type 3) are outside the cohort.
CONFIRMATION_START = 20262027
# The NHL reports a regular season game as game type 2.
REGULAR_SEASON_TYPE = 2
# A season later than any real season, so a confirmation plan scores every season
# the store holds from its first confirmation season onward.
OPEN_END = 99_999_999


def season_of(day: date) -> int:
    """Return the NHL season id that a date falls in.

    A season runs from September of its first year through the end of the next year.
    """
    first_year = day.year if day.month >= 9 else day.year - 1
    return first_year * 10000 + first_year + 1


@dataclass(frozen=True, slots=True)
class SeasonPlan:
    """The season ranges of one backtest. A test passes a short plan."""

    burn_in: int = ELO_BURN_IN
    fit_first: int = FIT_FIRST
    select_train: tuple[int, int] = SELECT_TRAIN
    select_validate: tuple[int, int] = SELECT_VALIDATE
    scored: tuple[int, int] = SCORED
    # Game types the plan scores. None keeps every game type the store holds.
    game_types: tuple[int, ...] | None = None
    # Score only games that start after this instant. A confirmation record uses its
    # registration cutoff, so a spent cohort is never scored twice.
    cutoff: datetime | None = None


def confirmation_plan(cutoff: datetime) -> SeasonPlan:
    """Return the plan of a confirmation run.

    The cohort is the regular season of the season the cutoff falls in, and every
    later season. Only games that start after the cutoff are scored.
    """
    # The floor keeps a record with an early cutoff from scoring exploration seasons.
    first_season = max(CONFIRMATION_START, season_of(cutoff.date()))
    return SeasonPlan(
        scored=(first_season, OPEN_END),
        game_types=(REGULAR_SEASON_TYPE,),
        cutoff=cutoff,
    )


def exploration_plan() -> SeasonPlan:
    """Return the plan of an exploration run: every season through 2025-26."""
    return SeasonPlan(scored=EXPLORATION)


def in_cohort(game: GameRow, plan: SeasonPlan) -> bool:
    """Return True when the plan scores this game."""
    if not plan.scored[0] <= game.season <= plan.scored[1]:
        return False
    if plan.game_types is not None and game.game_type not in plan.game_types:
        return False
    return plan.cutoff is None or game.start > plan.cutoff


def scored_label(plan: SeasonPlan) -> str:
    """Describe the seasons a plan scores, in words a reader can check."""
    if plan.scored[1] == OPEN_END:
        return f"seasons from {plan.scored[0]} onward"
    return f"seasons {plan.scored[0]} to {plan.scored[1]}"


DEFAULT_PLAN = SeasonPlan()
