"""Roster matchup and playoff probability entry points."""

import math
from collections.abc import Sequence
from dataclasses import dataclass

from hockey_model.models import MatchupModel, StandingsModel
from hockey_model.roster import validate_roster
from hockey_model.types import ProbabilityError, Projection, Roster, Standing


@dataclass(frozen=True, slots=True)
class MatchupResult:
    """Win probabilities and expected-goal intervals for two rosters."""

    home_win: float
    away_win: float
    home_goals: Projection
    away_goals: Projection


def matchup(home: Roster, away: Roster, model: MatchupModel, level: float = 0.8) -> MatchupResult:
    """Project a matchup between any two valid NHL or fantasy rosters."""
    if not 0.0 < level < 1.0:
        raise ValueError("level must be inside the open interval (0, 1)")
    validate_roster(home)
    validate_roster(away)
    home_win, away_win = model.win_probabilities(home, away)
    values = (home_win, away_win)
    if any(not math.isfinite(value) or not 0.0 <= value <= 1.0 for value in values):
        raise ProbabilityError(
            f"predict matchup: invalid win probabilities {values!r}; return finite values in [0, 1]"
        )
    if not math.isclose(home_win + away_win, 1.0, abs_tol=1e-9):
        raise ProbabilityError(
            f"predict matchup: win probabilities {values!r} do not sum to 1.0; "
            "include overtime and shootout wins in one side"
        )
    return MatchupResult(
        home_win,
        away_win,
        model.expected_goals(home, level),
        model.expected_goals(away, level),
    )


def playoff_probability(
    team_code: str,
    standings: Sequence[Standing],
    model: StandingsModel,
    level: float = 0.8,
) -> Projection:
    """Project rest-of-season playoff odds for a team present in ``standings``."""
    if not 0.0 < level < 1.0:
        raise ValueError("level must be inside the open interval (0, 1)")
    if all(standing.team_code != team_code for standing in standings):
        raise ValueError(
            f"project playoff probability for {team_code!r}: team is absent from standings; "
            "supply its current standing"
        )
    return model.playoff_odds(team_code, standings, level)
