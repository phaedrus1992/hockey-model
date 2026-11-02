"""Tests for roster construction and validation."""

from collections.abc import Mapping, Sequence
from datetime import date

import pytest

from hockey_model.roster import nhl_roster, validate_roster
from hockey_model.types import Player, Roster, Slot, SlotError


def _player(canonical_id: str, eligible: set[Slot]) -> Player:
    return Player(canonical_id, None, None, canonical_id, frozenset(eligible), None)


class FixedRosterSource:
    def __init__(self, table: Mapping[tuple[str, date], Sequence[Player]]) -> None:
        self.table = table

    def club_players(self, team_code: str, as_of: date) -> Sequence[Player]:
        return self.table.get((team_code, as_of), ())


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


def test_nhl_roster_returns_club_players_at_date() -> None:
    as_of = date(2026, 11, 1)
    player = _player("a", {Slot.C})
    roster = nhl_roster("TOR", as_of, FixedRosterSource({("TOR", as_of): (player,)}))
    assert roster == Roster("TOR", (player,), None)


def test_nhl_roster_unknown_team_or_empty_source_raises() -> None:
    with pytest.raises(ValueError, match="XYZ.*2026-11-01"):
        nhl_roster("XYZ", date(2026, 11, 1), FixedRosterSource({}))
