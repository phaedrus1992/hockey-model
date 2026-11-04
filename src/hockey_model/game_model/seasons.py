"""The seasons that the fit and the backtest use. A season is written as the NHL writes it."""

from dataclasses import dataclass
from datetime import date

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


@dataclass(frozen=True, slots=True)
class SeasonPlan:
    """The season ranges of one backtest. A test passes a short plan."""

    burn_in: int = ELO_BURN_IN
    fit_first: int = FIT_FIRST
    select_train: tuple[int, int] = SELECT_TRAIN
    select_validate: tuple[int, int] = SELECT_VALIDATE
    scored: tuple[int, int] = SCORED


DEFAULT_PLAN = SeasonPlan()


def season_of(day: date) -> int:
    """Return the NHL season that holds ``day``, such as 20262027 for November 2026.

    The season starts in July here. Preseason games in September belong to the season
    that starts that year, and no regular season game is played in July.
    """
    start = day.year if day.month >= 7 else day.year - 1
    return start * 10000 + start + 1
