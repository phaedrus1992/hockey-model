"""The starting goalie read that ESPN and Daily Faceoff both produce."""

from dataclasses import dataclass
from datetime import datetime

from hockey_model.game import StarterSource, StarterStatus


@dataclass(frozen=True, slots=True)
class StarterRead:
    """One source's report of the goalie who starts for one team in one game."""

    start: datetime
    team: str
    goalie_name: str
    status: StarterStatus
    source: StarterSource
