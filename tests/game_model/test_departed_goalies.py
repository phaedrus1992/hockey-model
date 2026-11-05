"""Tests for the guessed starter when a goalie has left the team."""

import sqlite3
from datetime import timedelta

import pytest
from seeding import FETCHED, add_game, add_goalie, add_starter_read, utc

from hockey_model.game import Game, MissingKind
from hockey_model.game_model.goalies import resolve_goalie

START = utc("2026-01-20T00:00")
AS_OF = utc("2026-01-19T16:00")
INGRAM = 11
WOLL = 12


@pytest.fixture
def season(store: sqlite3.Connection) -> sqlite3.Connection:
    """Ten TOR games. Ingram started seven of them and Woll three."""
    for number in range(1, 11):
        add_game(store, number, f"2026-01-{number:02d}T00:00")
        ingram = number % 10 > 3 or number == 10
        add_goalie(
            store, number, "TOR", INGRAM if ingram else WOLL, "C. Ingram" if ingram else "J. Woll"
        )
    return store


def _guess(conn: sqlite3.Connection, *, use_reads: bool = False, team: str = "TOR"):
    game = Game(100, "TOR", "BOS", START)
    return resolve_goalie(conn, game, team, AS_OF, use_reads=use_reads)


def _name(start) -> str | None:
    return None if start is None else start.player.full_name


def _played_for(conn: sqlite3.Connection, number: int, day: str, team: str, nhl_id: int) -> None:
    """Ingram appears in a game of ``team`` on ``day``."""
    add_game(conn, number, day, home=team, away="BOS")
    name = "C. Ingram" if nhl_id == INGRAM else "J. Woll"
    # A player row is added when the team changes, and its key holds the read time.
    add_goalie(conn, number, team, nhl_id, name, fetched_at=FETCHED + timedelta(hours=number))


def test_the_baseline_guess_is_the_goalie_with_most_starts(season: sqlite3.Connection) -> None:
    start, _ = _guess(season)
    assert _name(start) == "C. Ingram"


@pytest.mark.parametrize("use_reads", [True, False])
def test_a_goalie_who_left_before_the_cutoff_is_not_guessed(
    season: sqlite3.Connection, use_reads: bool
) -> None:
    _played_for(season, 20, "2026-01-12T00:00", "MTL", INGRAM)
    start, missing = _guess(season, use_reads=use_reads)
    assert _name(start) == "J. Woll"
    assert MissingKind.GOALIE_UNKNOWN in [m.kind for m in missing]


def test_a_departure_after_the_cutoff_changes_nothing(season: sqlite3.Connection) -> None:
    before, _ = _guess(season)
    _played_for(season, 20, "2026-01-19T20:00", "MTL", INGRAM)
    after, _ = _guess(season)
    assert _name(after) == _name(before) == "C. Ingram"


def test_a_goalie_who_came_back_is_a_member_again(season: sqlite3.Connection) -> None:
    _played_for(season, 20, "2026-01-12T00:00", "MTL", INGRAM)
    _played_for(season, 21, "2026-01-14T00:00", "TOR", INGRAM)
    start, _ = _guess(season)
    assert _name(start) == "C. Ingram"


def test_a_game_for_the_same_franchise_under_an_old_code_is_not_a_departure(
    store: sqlite3.Connection,
) -> None:
    for number in range(1, 4):
        add_game(store, number, f"2026-01-{number:02d}T00:00", home="ARI", away="BOS")
        add_goalie(store, number, "ARI", INGRAM, "C. Ingram")
    add_game(store, 4, "2026-01-05T00:00", home="UTA", away="BOS")
    add_goalie(store, 4, "UTA", INGRAM, "C. Ingram", fetched_at=FETCHED + timedelta(hours=4))
    start, _ = _guess(store, team="UTA")
    assert _name(start) == "C. Ingram"


def test_a_nominated_newcomer_is_not_filtered(season: sqlite3.Connection) -> None:
    # The source names Ingram for TOR, though the local data shows him with MTL.
    _played_for(season, 20, "2026-01-12T00:00", "MTL", INGRAM)
    add_starter_read(
        season, 100, "TOR", "espn", "C. Ingram", "confirmed", fetched_at="2026-01-19T15:00"
    )
    start, _ = _guess(season, use_reads=True)
    assert _name(start) == "C. Ingram"
    assert start is not None
    assert start.source.value == "espn"


def test_two_teams_at_the_same_start_time_is_a_conflict_not_a_departure(
    season: sqlite3.Connection,
) -> None:
    _played_for(season, 20, "2026-01-12T00:00", "MTL", INGRAM)
    _played_for(season, 21, "2026-01-12T00:00", "TOR", INGRAM)
    start, missing = _guess(season)
    assert _name(start) == "C. Ingram"
    assert any("conflict" in m.note and m.kind is MissingKind.GOALIE_UNKNOWN for m in missing)


def test_no_guess_when_every_candidate_has_left(season: sqlite3.Connection) -> None:
    _played_for(season, 20, "2026-01-12T00:00", "MTL", INGRAM)
    _played_for(season, 21, "2026-01-13T00:00", "NYR", WOLL)
    start, missing = _guess(season)
    assert start is None
    assert [m.kind for m in missing][-1] is MissingKind.GOALIE_UNKNOWN
    assert any("has left" in m.note for m in missing)


def test_a_game_that_is_not_final_is_not_evidence(season: sqlite3.Connection) -> None:
    add_game(season, 20, "2026-01-12T00:00", home="MTL", away="BOS", state="LIVE")
    add_goalie(season, 20, "MTL", INGRAM, "C. Ingram", fetched_at=FETCHED + timedelta(hours=20))
    start, _ = _guess(season)
    assert _name(start) == "C. Ingram"
