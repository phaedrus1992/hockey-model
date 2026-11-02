"""Tests for public domain value objects."""

import math

import pytest

from hockey_model.types import Player, Projection, Roster, Slot, Standing, Team


def _player(**changes: object) -> Player:
    values = {
        "canonical_id": "p-1",
        "yahoo_id": None,
        "nhl_id": None,
        "full_name": "A Player",
        "eligible": frozenset({Slot.C}),
        "team_code": None,
    }
    values.update(changes)
    return Player(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("field", ["point", "low", "high", "level"])
@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_projection_rejects_non_finite_values(field: str, value: float) -> None:
    values = {"point": 0.5, "low": 0.0, "high": 1.0, "level": 0.8}
    values[field] = value
    with pytest.raises(ValueError, match=f"{field} must be finite"):
        Projection(**values)


@pytest.mark.parametrize("level", [0.0, 1.0, -0.1, 1.5])
def test_projection_rejects_level_outside_open_unit_interval(level: float) -> None:
    with pytest.raises(ValueError, match="level"):
        Projection(point=0.5, low=0.0, high=1.0, level=level)


def test_projection_rejects_low_above_high() -> None:
    with pytest.raises(ValueError, match="low"):
        Projection(point=0.5, low=1.0, high=0.0, level=0.8)


def test_player_rejects_empty_canonical_id() -> None:
    with pytest.raises(ValueError, match="canonical_id"):
        _player(canonical_id="")


def test_player_rejects_no_eligible_positions() -> None:
    with pytest.raises(ValueError, match="eligible"):
        _player(eligible=frozenset())


def test_player_rejects_roster_only_eligibility() -> None:
    with pytest.raises(ValueError, match="roster-only"):
        _player(eligible=frozenset({Slot.BENCH}))


def test_player_source_fields_are_validated() -> None:
    with pytest.raises(ValueError, match="yahoo_id"):
        _player(yahoo_id=" ")
    with pytest.raises(ValueError, match="nhl_id"):
        _player(nhl_id=0)
    with pytest.raises(ValueError, match="team_code"):
        _player(team_code="")


def test_team_and_standing_validate_fields() -> None:
    assert Team("TOR", "Toronto Maple Leafs", "Atlantic", "Eastern").code == "TOR"
    with pytest.raises(ValueError, match="name"):
        Team("TOR", "", "Atlantic", "Eastern")
    with pytest.raises(ValueError, match="games_played"):
        Standing("TOR", -1, 0, 0, 1)
    with pytest.raises(ValueError, match="rank"):
        Standing("TOR", 0, 0, 0, 0)


def test_roster_rejects_duplicate_players() -> None:
    player = _player()
    with pytest.raises(ValueError, match="unique"):
        Roster("duplicate", (player, player))
