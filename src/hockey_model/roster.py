"""Roster construction and slot validation."""

from hockey_model.types import Player, Roster, Slot, SlotError

SKATER_SLOTS = frozenset({Slot.C, Slot.W, Slot.D})


def _slot_fits(player: Player, slot: Slot) -> bool:
    if slot is Slot.BENCH:
        return True
    if slot is Slot.UTIL:
        return bool(player.eligible & SKATER_SLOTS)
    return slot in player.eligible


def validate_roster(roster: Roster) -> None:
    """Raise ``SlotError`` when a roster assignment is unknown or ineligible."""
    if roster.slots is None:
        return
    players = {player.canonical_id: player for player in roster.players}
    for player_id, slot in roster.slots.items():
        player = players.get(player_id)
        if player is None:
            raise SlotError(
                f"validate roster {roster.name!r}: slot {slot} references unknown player "
                f"{player_id!r}; remove the assignment or add the player"
            )
        if not _slot_fits(player, slot):
            eligible = ", ".join(sorted(position.value for position in player.eligible))
            raise SlotError(
                f"validate roster {roster.name!r}: player {player_id!r} cannot fill {slot}; "
                f"assign an eligible slot ({eligible}) or bench"
            )
