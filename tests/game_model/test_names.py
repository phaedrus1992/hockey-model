"""Tests for goalie name matching."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from hockey_model.game_model.names import matching_players, name_key
from hockey_model.types import Player, Slot


def goalie(nhl_id: int, name: str) -> Player:
    return Player(f"nhl:{nhl_id}", None, nhl_id, name, frozenset({Slot.G}), "TOR")


@pytest.mark.parametrize(
    ("name", "key"),
    [
        ("Connor Ingram", ("c", "ingram")),
        ("C. Ingram", ("c", "ingram")),
        ("Ukko-Pekka Luukkonen", ("u", "luukkonen")),
        ("Jörgen Sögaard", ("j", "sogaard")),
        ("José Pérez", ("j", "perez")),
        ("A.J. Greer", ("a", "greer")),
        ("J.-F. Berube", ("j", "berube")),
        ("Jean-Francois Berube", ("j", "berube")),
        ("Alex De Smith", ("a", "smith")),
        ("Mads Søgaard Jr.", ("m", "søgaard")),
        ("Ingram", None),
        ("", None),
    ],
)
def test_name_key(name: str, key: tuple[str, str] | None) -> None:
    assert name_key(name) == key


def test_full_name_matches_initial_and_surname() -> None:
    players = [goalie(1, "C. Ingram"), goalie(2, "J. Campbell")]
    assert [p.nhl_id for p in matching_players("Connor Ingram", players)] == [1]


def test_different_initial_does_not_match() -> None:
    assert matching_players("Dan Ingram", [goalie(1, "C. Ingram")]) == []


def test_two_players_can_match() -> None:
    players = [goalie(1, "C. Ingram"), goalie(2, "Connor Ingram")]
    assert len(matching_players("Connor Ingram", players)) == 2


def test_accent_and_case_do_not_matter() -> None:
    assert matching_players("JOSE PEREZ", [goalie(1, "J. Pérez")])


@given(st.text(max_size=30))
def test_name_key_never_raises(name: str) -> None:
    key = name_key(name)
    assert key is None or (len(key[0]) == 1 and key[1])


_SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}
_WORDS = st.text(
    alphabet=st.characters(min_codepoint=97, max_codepoint=122), min_size=2, max_size=8
).filter(lambda word: word not in _SUFFIXES)


@given(_WORDS, _WORDS)
def test_name_key_ignores_case_suffix_and_an_initial_dot(first: str, last: str) -> None:
    key = name_key(f"{first} {last}")
    assert key == (first[0], last)
    assert name_key(f"{first} {last}".upper()) == key
    assert name_key(f"{first} {last} Jr.") == key
    assert name_key(f"{first[0]}. {last}") == key
