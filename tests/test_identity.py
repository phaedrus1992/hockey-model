"""Tests for strict player identity resolution."""

import unicodedata

import pytest
from hypothesis import given
from hypothesis import strategies as st

from hockey_model.identity import Catalog, resolve_player
from hockey_model.types import AmbiguousPlayerError, Player, Slot, UnknownPlayerError


def _player(
    canonical_id: str,
    name: str,
    *,
    yahoo_id: str | None = None,
    nhl_id: int | None = None,
    team_code: str | None = "TOR",
) -> Player:
    return Player(canonical_id, yahoo_id, nhl_id, name, frozenset({Slot.C}), team_code)


@pytest.fixture
def catalog() -> Catalog:
    return Catalog([_player("p-mcdavid", "Connor McDavid", yahoo_id="y-1", nhl_id=8478402)])


def test_resolve_by_each_exact_id(catalog: Catalog) -> None:
    assert catalog.resolve("p-mcdavid").full_name == "Connor McDavid"
    assert catalog.resolve("y-1").canonical_id == "p-mcdavid"
    assert catalog.resolve(8478402).canonical_id == "p-mcdavid"


def test_name_ignores_case_and_accents() -> None:
    catalog = Catalog([_player("p-chara", "Zdeno Chára")])
    assert catalog.resolve("ZDENO CHARA").canonical_id == "p-chara"


def test_name_does_not_match_nickname() -> None:
    catalog = Catalog([_player("p-mcdavid", "Connor McDavid")])
    with pytest.raises(UnknownPlayerError):
        catalog.resolve("Conn")


def test_ambiguous_name_lists_active_and_retired_candidates() -> None:
    catalog = Catalog([_player("p-a", "Sam Smith"), _player("p-b", "Sam Smith", team_code=None)])
    with pytest.raises(AmbiguousPlayerError) as info:
        catalog.resolve("Sam Smith")
    assert {candidate.canonical_id for candidate in info.value.candidates} == {"p-a", "p-b"}
    assert "retry with an ID" in str(info.value)


@pytest.mark.parametrize("ref", ["p-missing", 123])
def test_unknown_reference_raises(ref: str | int) -> None:
    with pytest.raises(UnknownPlayerError, match=str(ref)):
        Catalog([]).resolve(ref)


@pytest.mark.parametrize(
    ("players", "label"),
    [
        ([_player("same", "A"), _player("same", "B")], "canonical ID"),
        ([_player("a", "A", yahoo_id="same"), _player("b", "B", yahoo_id="same")], "source ID"),
        ([_player("a", "A", nhl_id=1), _player("b", "B", nhl_id=1)], "NHL ID"),
    ],
)
def test_duplicate_ids_are_rejected(players: list[Player], label: str) -> None:
    with pytest.raises(ValueError, match=label):
        Catalog(players)


@given(st.sampled_from(["Éric Bélanger", "Zdeno Chára", "Jesús Sánchez"]))
def test_case_and_accent_folding_round_trips(name: str) -> None:
    player = _player("p", name)
    decomposed = unicodedata.normalize("NFKD", name)
    unaccented = "".join(char for char in decomposed if not unicodedata.combining(char))
    assert Catalog([player]).resolve(name.swapcase()) == player
    assert resolve_player(unaccented, Catalog([player])) == player
