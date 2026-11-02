"""Tests for roster construction and validation."""

import pytest

from hockey_model.roster import validate_roster
from hockey_model.types import Player, Roster, Slot, SlotError


def _player(canonical_id: str, eligible: set[Slot]) -> Player:
    return Player(canonical_id, None, None, canonical_id, frozenset(eligible), None)


def test_goalie_cannot_fill_forward_slot() -> None:
    roster = Roster("t", (_player("g", {Slot.G}),), {"g": Slot.W})
    with pytest.raises(SlotError, match="g.*W"):
        validate_roster(roster)


@pytest.mark.parametrize("slot", [Slot.C, Slot.W, Slot.UTIL, Slot.BENCH])
def test_multi_position_skater_fits_supported_slots(slot: Slot) -> None:
    roster = Roster("t", (_player("c", {Slot.C, Slot.W}),), {"c": slot})
    validate_roster(roster)


def test_goalie_cannot_fill_utility_slot() -> None:
    roster = Roster("t", (_player("g", {Slot.G}),), {"g": Slot.UTIL})
    with pytest.raises(SlotError, match="g.*UTIL"):
        validate_roster(roster)


def test_slot_referencing_unknown_player_raises() -> None:
    roster = Roster("t", (_player("a", {Slot.C}),), {"ghost": Slot.C})
    with pytest.raises(SlotError, match="ghost"):
        validate_roster(roster)


def test_missing_slot_is_valid_and_unslotted_player_counts_later() -> None:
    validate_roster(Roster("t", (_player("a", {Slot.C}),), {}))


def test_no_slots_means_no_check() -> None:
    validate_roster(Roster("t", (_player("g", {Slot.G}),), None))


def test_empty_roster_is_valid() -> None:
    validate_roster(Roster("t", (), {}))
