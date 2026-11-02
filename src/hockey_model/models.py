"""Model boundaries and deterministic in-memory model fakes."""

from collections.abc import Mapping, Sequence
from typing import Protocol, runtime_checkable

from hockey_model.types import MissingProjectionError, Player, Projection, Roster, Standing


@runtime_checkable
class StatModel(Protocol):
    """Project one statistic for one player."""

    def project(self, player: Player, stat: str, horizon_games: int, level: float) -> Projection:
        """Return the player's projection."""
        ...


@runtime_checkable
class JointModel(Protocol):
    """Project a true joint total for a group of players."""

    def project_total(
        self, players: Sequence[Player], stat: str, horizon_games: int, level: float
    ) -> Projection:
        """Return the group projection without summing marginal intervals."""
        ...


@runtime_checkable
class StandingsModel(Protocol):
    """Project a team's rest-of-season playoff probability."""

    def playoff_odds(
        self, team_code: str, standings: Sequence[Standing], level: float
    ) -> Projection:
        """Return the team's playoff projection."""
        ...


@runtime_checkable
class MatchupModel(Protocol):
    """Project a head-to-head matchup between two rosters."""

    def win_probabilities(self, home: Roster, away: Roster) -> tuple[float, float]:
        """Return home and away win probabilities, including overtime and shootouts."""
        ...

    def expected_goals(self, team: Roster, level: float) -> Projection:
        """Return the team's expected goals projection."""
        ...


class FixedStatModel:
    """A deterministic stat model backed by ``(player ID, stat)`` keys."""

    def __init__(self, table: Mapping[tuple[str, str], Projection]) -> None:
        self._table = dict(table)

    def project(self, player: Player, stat: str, horizon_games: int, level: float) -> Projection:
        """Return a stored projection or raise when the key is absent."""
        del horizon_games, level
        try:
            return self._table[(player.canonical_id, stat)]
        except KeyError as exc:
            raise MissingProjectionError(
                f"project player {player.canonical_id!r} stat {stat!r}: no projection; "
                "provide model data or remove the player from the counting roster"
            ) from exc
