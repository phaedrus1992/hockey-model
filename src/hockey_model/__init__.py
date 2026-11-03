"""Player stat rate and game win models for hockey."""

from importlib.metadata import version

from hockey_model.game import (
    Game,
    GamePrediction,
    GoalieStart,
    MissingInput,
    MissingKind,
    StarterSource,
    StarterStatus,
    game_win_probability,
)
from hockey_model.identity import Catalog
from hockey_model.matchup import MatchupResult, matchup, playoff_probability
from hockey_model.models import (
    FixedStatModel,
    GameModel,
    JointModel,
    MatchupModel,
    RosterSource,
    StandingsModel,
    StatModel,
)
from hockey_model.projections import RATE_STATS, TeamProjection, project_player, project_team
from hockey_model.roster import nhl_roster, validate_roster
from hockey_model.types import (
    AmbiguousPlayerError,
    HockeyModelError,
    MissingProjectionError,
    ModelNotConfiguredError,
    Player,
    ProbabilityError,
    Projection,
    RateStatAggregationError,
    Roster,
    Slot,
    SlotError,
    Standing,
    Team,
    UnknownPlayerError,
)

__version__ = version("hockey-model")

__all__ = [
    "RATE_STATS",
    "AmbiguousPlayerError",
    "Catalog",
    "FixedStatModel",
    "Game",
    "GameModel",
    "GamePrediction",
    "GoalieStart",
    "HockeyModelError",
    "JointModel",
    "MatchupModel",
    "MatchupResult",
    "MissingInput",
    "MissingKind",
    "MissingProjectionError",
    "ModelNotConfiguredError",
    "Player",
    "ProbabilityError",
    "Projection",
    "RateStatAggregationError",
    "Roster",
    "RosterSource",
    "Slot",
    "SlotError",
    "StarterSource",
    "StarterStatus",
    "Standing",
    "StandingsModel",
    "StatModel",
    "Team",
    "TeamProjection",
    "UnknownPlayerError",
    "game_win_probability",
    "matchup",
    "nhl_roster",
    "playoff_probability",
    "project_player",
    "project_team",
    "validate_roster",
]
