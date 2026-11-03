"""Public input and output types for the NHL game win probability model."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum

from hockey_model.matchup import check_win_pair
from hockey_model.models import GameModel
from hockey_model.types import Player, Projection


class StarterStatus(StrEnum):
    """How certain a goalie start is."""

    CONFIRMED = "confirmed"
    LIKELY = "likely"
    UNKNOWN = "unknown"


class StarterSource(StrEnum):
    """Which source reported a goalie start."""

    ESPN = "espn"
    DAILY_FACEOFF = "daily_faceoff"
    NHL_BOXSCORE = "nhl_boxscore"
    MODEL_GUESS = "model_guess"


class MissingKind(StrEnum):
    """A model input that was absent or weak, so the prediction is less certain."""

    GOALIE_UNCONFIRMED = "goalie_unconfirmed"
    GOALIE_UNKNOWN = "goalie_unknown"
    XG_FORM = "xg_form"
    GOALIE_FORM = "goalie_form"
    STALE_SOURCE = "stale_source"
    LATE_RUN = "late_run"


@dataclass(frozen=True, slots=True)
class GoalieStart:
    """A goalie expected to start for one team, with its source and read time."""

    player: Player
    status: StarterStatus
    source: StarterSource
    read_at: datetime

    def __post_init__(self) -> None:
        _require_aware(self.read_at, "read_at")


@dataclass(frozen=True, slots=True)
class Game:
    """One scheduled NHL game, with optional goalie starts."""

    game_id: int
    home: str
    away: str
    start: datetime
    home_goalie: GoalieStart | None = None
    away_goalie: GoalieStart | None = None

    def __post_init__(self) -> None:
        if self.game_id <= 0:
            raise ValueError(f"game_id must be positive, got {self.game_id}")
        if not self.home.strip() or not self.away.strip():
            raise ValueError("home and away team codes must not be empty")
        if self.home == self.away:
            raise ValueError(f"home and away must differ, both are {self.home!r}")
        _require_aware(self.start, "start")


@dataclass(frozen=True, slots=True)
class MissingInput:
    """One input the model did not have, or had only in a weak form."""

    kind: MissingKind
    team: str | None
    note: str


@dataclass(frozen=True, slots=True)
class GamePrediction:
    """Win probabilities and goal projections for one game."""

    home_win: float
    away_win: float
    home_goals: Projection
    away_goals: Projection
    missing: tuple[MissingInput, ...]
    credits: tuple[str, ...]
    made_after_start: bool = False


def game_win_probability(
    game: Game,
    model: GameModel,
    *,
    as_of: datetime | None = None,
    level: float = 0.8,
) -> GamePrediction:
    """Predict a game as known at ``as_of``, defaulting to the current UTC time."""
    if not 0.0 < level < 1.0:
        raise ValueError(f"level must be inside the open interval (0, 1), got {level}")
    moment = datetime.now(UTC) if as_of is None else as_of
    _require_aware(moment, "as_of")
    result = model.predict(game, moment, level)
    check_win_pair((result.home_win, result.away_win), "predict game")
    return replace(result, made_after_start=moment >= game.start)


def _require_aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware UTC, got a naive datetime")
