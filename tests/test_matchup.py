"""Tests for matchup and playoff projections."""

import math
from collections.abc import Sequence

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from hockey_model.matchup import check_win_pair, matchup, playoff_probability
from hockey_model.types import (
    Player,
    ProbabilityError,
    Projection,
    Roster,
    Slot,
    SlotError,
    Standing,
)

GOALS = Projection(3.0, 1.0, 5.0, 0.8)


def _player(canonical_id: str, eligible: set[Slot] | None = None) -> Player:
    return Player(
        canonical_id,
        None,
        None,
        canonical_id,
        frozenset(eligible or {Slot.C}),
        None,
    )


class FixedMatchupModel:
    def __init__(self, home_win: float, away_win: float | None = None) -> None:
        self.probabilities = (home_win, 1.0 - home_win if away_win is None else away_win)
        self.teams: list[str] = []

    def win_probabilities(self, home: Roster, away: Roster) -> tuple[float, float]:
        return self.probabilities

    def expected_goals(self, team: Roster, level: float) -> Projection:
        self.teams.append(team.name)
        return Projection(GOALS.point, GOALS.low, GOALS.high, level)


class FixedStandingsModel:
    def __init__(self) -> None:
        self.call: tuple[str, Sequence[Standing], float] | None = None

    def playoff_odds(
        self, team_code: str, standings: Sequence[Standing], level: float
    ) -> Projection:
        self.call = (team_code, standings, level)
        return Projection(0.7, 0.5, 0.9, level)


@pytest.fixture
def rosters() -> tuple[Roster, Roster]:
    return Roster("home", (_player("h"),)), Roster("away", (_player("a"),))


def test_win_probabilities_sum_to_one(rosters: tuple[Roster, Roster]) -> None:
    home, away = rosters
    result = matchup(home, away, FixedMatchupModel(home_win=0.55), level=0.8)
    assert result.home_win == pytest.approx(0.55)
    assert result.away_win == pytest.approx(0.45)
    assert result.home_goals == result.away_goals == GOALS
    assert result.home_win + result.away_win == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("home_win", "away_win", "message"),
    [(0.6, 0.6, "sum"), (math.nan, 0.5, "finite"), (-0.1, 1.1, "finite")],
)
def test_model_returning_invalid_pair_raises(
    rosters: tuple[Roster, Roster], home_win: float, away_win: float, message: str
) -> None:
    with pytest.raises(ProbabilityError, match=message):
        matchup(*rosters, FixedMatchupModel(home_win, away_win))


def test_matchup_validates_both_rosters(rosters: tuple[Roster, Roster]) -> None:
    _, away = rosters
    bad = Roster("bad", (_player("g", {Slot.G}),), {"g": Slot.W})
    with pytest.raises(SlotError):
        matchup(bad, away, FixedMatchupModel(0.5))


def test_matchup_accepts_nhl_and_fantasy_rosters_the_same_way() -> None:
    nhl = Roster("NHL", (_player("a"),), None)
    fantasy = Roster("fantasy", (_player("b"),), {"b": Slot.C})
    model = FixedMatchupModel(0.5)
    matchup(nhl, fantasy, model)
    assert model.teams == ["NHL", "fantasy"]


def test_playoff_probability_returns_projection_with_level() -> None:
    standings = [Standing("TOR", 10, 12, 5, 8)]
    model = FixedStandingsModel()
    projection = playoff_probability("TOR", standings, model, level=0.9)
    assert projection.level == 0.9
    assert model.call == ("TOR", standings, 0.9)


def test_playoff_probability_requires_team_in_standings() -> None:
    with pytest.raises(ValueError, match="TOR.*absent"):
        playoff_probability("TOR", [], FixedStandingsModel())


@pytest.mark.parametrize("function", ["matchup", "playoffs"])
def test_probability_entry_points_reject_invalid_level(
    function: str, rosters: tuple[Roster, Roster]
) -> None:
    with pytest.raises(ValueError, match="level"):
        if function == "matchup":
            matchup(*rosters, FixedMatchupModel(0.5), level=1.0)
        else:
            playoff_probability("TOR", [Standing("TOR", 0, 0, 0, 1)], FixedStandingsModel(), 0.0)


@pytest.mark.parametrize(
    ("point", "low", "high"),
    [(-0.1, 0.0, 1.0), (1.1, 0.0, 1.0), (0.5, -0.1, 0.9), (0.5, 0.1, 1.1)],
)
def test_playoff_probability_rejects_out_of_range_model_values(
    point: float, low: float, high: float
) -> None:
    class InvalidStandingsModel:
        def playoff_odds(
            self, team_code: str, standings: Sequence[Standing], level: float
        ) -> Projection:
            return Projection(point, low, high, level)

    with pytest.raises(ProbabilityError, match=r"playoff.*TOR.*\[0, 1\]"):
        playoff_probability("TOR", [Standing("TOR", 10, 12, 5, 8)], InvalidStandingsModel())


@pytest.mark.parametrize("point", [0.0, 1.0])
def test_playoff_probability_accepts_closed_interval_boundaries(point: float) -> None:
    class BoundaryStandingsModel:
        def playoff_odds(
            self, team_code: str, standings: Sequence[Standing], level: float
        ) -> Projection:
            return Projection(point, 0.0, 1.0, level)

    result = playoff_probability("TOR", [Standing("TOR", 10, 12, 5, 8)], BoundaryStandingsModel())
    assert result == Projection(point, 0.0, 1.0, 0.8)


@settings(max_examples=60, deadline=None)
@given(st.floats(min_value=0.0, max_value=1.0), st.floats(min_value=-1.0, max_value=2.0))
def test_a_win_pair_passes_only_when_it_is_a_probability_pair_summing_to_one(
    home: float, away: float
) -> None:
    valid = 0.0 <= away <= 1.0 and math.isclose(home + away, 1.0, abs_tol=1e-9)
    if valid:
        check_win_pair((home, away), "op")
    else:
        with pytest.raises(ProbabilityError):
            check_win_pair((home, away), "op")


@given(st.lists(st.floats(allow_nan=True), max_size=5).filter(lambda v: len(v) != 2))
def test_a_win_pair_of_the_wrong_length_is_refused(values: list[float]) -> None:
    with pytest.raises(ProbabilityError):
        check_win_pair(values, "op")
