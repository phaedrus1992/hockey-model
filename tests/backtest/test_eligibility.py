"""Tests for the season counts and the eligibility of a backtest."""

import math
import sqlite3

import pytest
from seeding import add_game

from hockey_model.backtest.eligibility import (
    SeasonCount,
    ineligibility_reasons,
    season_counts,
)
from hockey_model.backtest.metrics import MIN_BLOCK_LENGTH, MIN_INDEPENDENT_BLOCKS
from hockey_model.game_model.seasons import (
    EXPECTED_REGULAR_GAMES,
    MIN_SEASON_COVERAGE,
    SeasonPlan,
)

PLAN = SeasonPlan(scored=(20232024, 20252026))
ENOUGH = MIN_INDEPENDENT_BLOCKS * MIN_BLOCK_LENGTH


def _full(season: int) -> list[tuple[int, int]]:
    return [(season, 2)] * EXPECTED_REGULAR_GAMES[season]


def test_a_listed_season_with_no_scored_game_is_still_counted(store: sqlite3.Connection) -> None:
    counts = season_counts(store, _full(20232024) + _full(20242025), PLAN)
    by_season = {c.season: c for c in counts if c.game_type == 2}
    assert by_season[20252026] == SeasonCount(20252026, 2, 0, 1312, 0)
    assert by_season[20232024].scored == 1312


def test_counts_are_split_by_game_type_and_only_regular_seasons_have_an_expected_count(
    store: sqlite3.Connection,
) -> None:
    scored = _full(20232024) + [(20232024, 3)] * 40
    counts = {(c.season, c.game_type): c for c in season_counts(store, scored, PLAN)}
    assert counts[(20232024, 3)] == SeasonCount(20232024, 3, 40, None, 0)
    assert counts[(20232024, 2)].expected == 1312


def test_a_plan_without_regular_games_expects_no_season(store: sqlite3.Connection) -> None:
    playoffs = SeasonPlan(scored=(20232024, 20252026), game_types=(3,))
    counts = season_counts(store, [(20232024, 3)] * 5, playoffs)
    assert [(c.season, c.game_type, c.expected) for c in counts] == [(20232024, 3, None)]


def test_unresolved_games_are_counted_apart_from_scored_games(store: sqlite3.Connection) -> None:
    add_game(store, 1, "2026-01-10T00:00", season=20252026)
    add_game(store, 2, "2026-01-01T00:00", state="LIVE", season=20252026)
    add_game(store, 3, "2026-01-10T00:00", state="FUT", season=20252026)
    counts = {c.season: c for c in season_counts(store, [], PLAN) if c.game_type == 2}
    # Game 2 started far before the newest final game and never finished. Game 3 is not due.
    assert counts[20252026].unresolved == 1


def test_a_store_with_no_final_game_has_no_unresolved_games(store: sqlite3.Connection) -> None:
    add_game(store, 1, "2026-01-01T00:00", state="LIVE", season=20252026)
    assert all(c.unresolved == 0 for c in season_counts(store, [], PLAN))


def _reasons(conn: sqlite3.Connection, scored: list[tuple[int, int]]) -> tuple[str, ...]:
    return ineligibility_reasons(season_counts(conn, scored, PLAN), len(scored))


def test_full_seasons_with_enough_blocks_are_eligible(store: sqlite3.Connection) -> None:
    scored = _full(20232024) + _full(20242025) + _full(20252026)
    assert _reasons(store, scored) == ()


def test_a_missing_scored_season_is_a_reason(store: sqlite3.Connection) -> None:
    reasons = _reasons(store, _full(20232024) + _full(20242025))
    assert reasons == ("season 20252026 has no scored regular season games; expected 1312",)


def test_a_partial_season_is_a_reason_below_the_coverage_floor(store: sqlite3.Connection) -> None:
    floor = math.ceil(1312 * MIN_SEASON_COVERAGE)
    full = _full(20232024) + _full(20242025)
    (reason,) = _reasons(store, full + [(20252026, 2)] * (floor - 1))
    assert f"season 20252026 has {floor - 1} scored regular season games" in reason
    assert _reasons(store, full + [(20252026, 2)] * floor) == ()


def test_too_few_blocks_is_a_reason_even_with_covered_seasons() -> None:
    reasons = ineligibility_reasons((), ENOUGH - 1)
    assert len(reasons) == 1
    assert "independent blocks" in reasons[0]


@pytest.mark.parametrize("games", [0, 1, 2, MIN_BLOCK_LENGTH])
def test_samples_of_one_two_and_one_block_are_ineligible(games: int) -> None:
    assert any("independent blocks" in r for r in ineligibility_reasons((), games))


def test_an_unlisted_season_is_not_checked_for_coverage() -> None:
    counts = (SeasonCount(20262027, 2, 3, None, 0),)
    assert ineligibility_reasons(counts, ENOUGH) == ()
