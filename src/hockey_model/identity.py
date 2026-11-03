"""Strict player identity resolution."""

import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Sequence

from hockey_model.types import AmbiguousPlayerError, Player, UnknownPlayerError


def _normalize_name(name: str) -> str:
    decomposed = unicodedata.normalize("NFKD", name)
    unaccented = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return unaccented.casefold()


class Catalog:
    """An immutable searchable catalog of active and retired players."""

    def __init__(self, players: Sequence[Player]) -> None:
        self.players = tuple(players)
        self._canonical = self._unique_index(
            ((player.canonical_id, player) for player in self.players), "canonical ID"
        )
        source_pairs = (
            (source_id, player)
            for player in self.players
            for source_id in (player.yahoo_id,)
            if source_id is not None
        )
        self._source = self._unique_index(source_pairs, "source ID")
        for source_id in self._canonical.keys() & self._source.keys():
            if self._canonical[source_id] != self._source[source_id]:
                raise ValueError(f"duplicate string ID {source_id!r} in player catalog")
        self._string_ids = self._source | self._canonical
        self._nhl = self._unique_index(
            ((player.nhl_id, player) for player in self.players if player.nhl_id is not None),
            "NHL ID",
        )
        names: defaultdict[str, list[Player]] = defaultdict(list)
        for player in self.players:
            names[_normalize_name(player.full_name)].append(player)
        self._names = {name: tuple(matches) for name, matches in names.items()}

    @staticmethod
    def _unique_index(pairs: Iterable[tuple[object, Player]], label: str) -> dict[object, Player]:
        result: dict[object, Player] = {}
        for key, player in pairs:
            if key in result:
                raise ValueError(f"duplicate {label} {key!r} in player catalog")
            result[key] = player
        return result

    def resolve(self, ref: str | int) -> Player:
        """Resolve an exact ID or a unique case- and accent-insensitive full name."""
        if isinstance(ref, int):
            try:
                return self._nhl[ref]
            except KeyError as exc:
                raise UnknownPlayerError(ref) from exc
        exact = self._string_ids.get(ref)
        if exact is not None:
            return exact
        matches = self._names.get(_normalize_name(ref), ())
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise AmbiguousPlayerError(ref, matches)
        raise UnknownPlayerError(ref)
