"""Player and roster stat projection entry points."""

from collections.abc import Mapping
from dataclasses import dataclass

from hockey_model.models import JointModel, StatModel
from hockey_model.roster import validate_roster
from hockey_model.types import Player, Projection, RateStatAggregationError, Roster, Slot
from hockey_model.validation import stat_domain, validate_projection

RATE_STATS = frozenset({"save_pct", "goals_against_average", "gaa", "shooting_pct"})


@dataclass(frozen=True, slots=True)
class TeamProjection:
    """A joint roster total and its per-player marginal projections."""

    total: Projection
    breakdown: Mapping[str, Projection]


def _validate_request(horizon_games: int, level: float) -> None:
    if horizon_games <= 0:
        raise ValueError("horizon_games must be positive")
    if not 0.0 < level < 1.0:
        raise ValueError("level must be inside the open interval (0, 1)")


def project_player(
    player: Player,
    stat: str,
    model: StatModel,
    horizon_games: int = 1,
    level: float = 0.8,
) -> Projection:
    """Project one player statistic over a positive game horizon."""
    _validate_request(horizon_games, level)
    projection = model.project(player, stat, horizon_games, level)
    return validate_projection(
        projection, level, f"project {stat} for {player.canonical_id!r}", stat_domain(stat)
    )


def _counting_players(roster: Roster) -> tuple[Player, ...]:
    if roster.slots is None:
        return roster.players
    return tuple(
        player
        for player in roster.players
        if roster.slots.get(player.canonical_id) is not Slot.BENCH
    )


def project_team(
    roster: Roster,
    stat: str,
    model: StatModel,
    joint: JointModel,
    *,
    horizon_games: int = 1,
    level: float = 0.8,
) -> TeamProjection:
    """Project a roster total with a true joint interval and marginal breakdown."""
    _validate_request(horizon_games, level)
    validate_roster(roster)
    if stat in RATE_STATS:
        raise RateStatAggregationError(
            f"project team {roster.name!r} stat {stat!r}: rate stats cannot be summed; "
            "request player projections instead"
        )
    players = _counting_players(roster)
    if not players:
        return TeamProjection(Projection(0.0, 0.0, 0.0, level), {})
    domain = stat_domain(stat)
    breakdown = {
        player.canonical_id: validate_projection(
            model.project(player, stat, horizon_games, level),
            level,
            f"project {stat} for {player.canonical_id!r}",
            domain,
        )
        for player in players
    }
    total = validate_projection(
        joint.project_total(players, stat, horizon_games, level),
        level,
        f"project the {stat} total of team {roster.name!r}",
        domain,
    )
    return TeamProjection(total, breakdown)
