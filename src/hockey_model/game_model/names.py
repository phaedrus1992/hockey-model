"""Match a goalie name from one source to the players of the store.

The NHL boxscore writes a name as an initial and a surname, such as ``C. Ingram``.
ESPN and Daily Faceoff write the full name, such as ``Connor Ingram``. Two names match
when they have the same first initial and the same last word.
"""

import unicodedata
from collections.abc import Sequence

from hockey_model.types import Player


def _plain(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


_SUFFIXES = frozenset({"jr", "sr", "ii", "iii", "iv"})


def name_key(name: str) -> tuple[str, str] | None:
    """Return the first initial and the last word of ``name``, or ``None`` for one word.

    The last word is the surname. A multi-word surname still matches, because both
    spellings of a name end in the same word.
    """
    words = [w for w in _plain(name).replace(".", " ").replace("-", " ").split() if w]
    while len(words) > 1 and words[-1] in _SUFFIXES:
        words.pop()
    if len(words) < 2:  # noqa: PLR2004  # a name needs a first name or initial and a surname
        return None
    return words[0][0], words[-1]


def matching_players(name: str, players: Sequence[Player]) -> list[Player]:
    """Return every player of ``players`` whose name matches ``name``."""
    key = name_key(name)
    if key is None:
        return []
    return [player for player in players if name_key(player.full_name) == key]
