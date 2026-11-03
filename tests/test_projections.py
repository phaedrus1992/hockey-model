"""Tests for player and roster projections."""

from collections.abc import Sequence

import pytest
from hypothesis import given
from hypothesis import strategies as st

from hockey_model.models import FixedStatModel
from hockey_model.projections import RATE_STATS, TeamProjection, project_player, project_team
from hockey_model.types import (
    MissingProjectionError,
    Player,
    Projection,
    RateStatAggregationError,
    Roster,
    Slot,
)

P_04 = Projection(0.4, 0.1, 0.7, 0.8)
JOINT = Projection(0.9, 0.2, 1.8, 0.8)


def _player(canonical_id: str) -> Player:
    return Player(canonical_id, None, None, canonical_id, frozenset({Slot.C}), None)


class SpyStatModel:
    def __init__(self, result: Projection) -> None:
        self.result = result
        self.calls: list[tuple[Player, str, int, float]] = []

    def project(self, player: Player, stat: str, horizon_games: int, level: float) -> Projection:
        self.calls.append((player, stat, horizon_games, level))
        return self.result


class SpyJointModel:
    def __init__(self, result: Projection = JOINT) -> None:
        self.result = result
        self.calls: list[tuple[Sequence[Player], str, int, float]] = []

    def project_total(
        self, players: Sequence[Player], stat: str, horizon_games: int, level: float
    ) -> Projection:
        self.calls.append((players, stat, horizon_games, level))
        return self.result


def test_empty_roster_returns_zero_total_without_calling_models() -> None:
    model = SpyStatModel(P_04)
    joint = SpyJointModel()
    result = project_team(Roster("t", (), None), "goals", model, joint)
    assert result == TeamProjection(Projection(0.0, 0.0, 0.0, 0.8), {})
    assert model.calls == [] and joint.calls == []


def test_bench_player_without_projection_is_excluded() -> None:
    roster = Roster("t", (_player("a"), _player("b")), {"a": Slot.C, "b": Slot.BENCH})
    result = project_team(roster, "goals", FixedStatModel({("a", "goals"): P_04}), SpyJointModel())
    assert set(result.breakdown) == {"a"}


def test_starter_or_unslotted_player_without_projection_raises() -> None:
    for slots in ({"a": Slot.C}, {}):
        roster = Roster("t", (_player("a"),), slots)
        with pytest.raises(MissingProjectionError, match="a"):
            project_team(roster, "goals", FixedStatModel({}), SpyJointModel())


@pytest.mark.parametrize("stat", sorted(RATE_STATS))
def test_rate_stat_team_total_raises_even_for_empty_roster(stat: str) -> None:
    with pytest.raises(RateStatAggregationError, match=stat):
        project_team(Roster("t", (), None), stat, FixedStatModel({}), SpyJointModel())


def test_team_total_comes_from_joint_model_not_summed_marginals() -> None:
    players = (_player("a"), _player("b"))
    model = FixedStatModel({("a", "goals"): P_04, ("b", "goals"): P_04})
    result = project_team(Roster("t", players), "goals", model, SpyJointModel())
    assert result.total == JOINT
    assert result.total.point != sum(item.point for item in result.breakdown.values())


@given(level=st.floats(min_value=0.01, max_value=0.99, allow_nan=False))
def test_player_projection_passes_level_and_horizon_through(level: float) -> None:
    returned = Projection(0.4, 0.1, 0.7, level)
    model = SpyStatModel(returned)
    player = _player("a")
    assert project_player(player, "goals", model, horizon_games=5, level=level) == returned
    assert model.calls == [(player, "goals", 5, level)]


@pytest.mark.parametrize(("horizon", "level"), [(0, 0.8), (1, 0.0), (1, 1.0)])
def test_invalid_projection_request_is_rejected(horizon: int, level: float) -> None:
    with pytest.raises(ValueError):
        project_player(_player("a"), "goals", SpyStatModel(P_04), horizon, level)
