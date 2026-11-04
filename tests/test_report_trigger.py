"""Tests for the trigger that decides when the daily report runs."""

from datetime import UTC, date, datetime

import pytest

from hockey_model.report_trigger import first_puck_drop, is_due, next_trigger


def at(text: str) -> datetime:
    """Parse ``2026-11-04T12:30`` as UTC."""
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


DAY = date(2026, 11, 4)
FIRST_PUCK_DROP_2PM = at("2026-11-04T14:00")


@pytest.mark.parametrize(
    ("now", "runs"),
    [
        ("2026-11-04T00:05", False),
        ("2026-11-04T10:30", False),
        ("2026-11-04T11:59", False),
        ("2026-11-04T12:00", True),
        ("2026-11-04T12:20", True),
        # Later triggers still pass the due check. The release check stops them.
        ("2026-11-04T14:05", True),
        ("2026-11-04T22:00", True),
    ],
)
def test_first_puck_drop_at_two_pm_runs_at_noon_trigger(now: str, runs: bool) -> None:
    assert is_due(at(now), FIRST_PUCK_DROP_2PM) is runs


def test_trigger_exactly_at_first_puck_drop_runs_the_trigger_before() -> None:
    assert is_due(at("2026-11-04T12:00"), at("2026-11-04T14:00")) is True
    assert is_due(at("2026-11-04T13:59"), at("2026-11-04T14:00")) is True


def test_slot_for_a_late_trigger_is_its_own_slot() -> None:
    assert next_trigger(at("2026-11-04T12:50")) == at("2026-11-04T14:00")


def test_no_games_waits_for_the_last_trigger_of_the_day() -> None:
    first = first_puck_drop(DAY, [])
    assert first == at("2026-11-05T00:00")
    assert is_due(at("2026-11-04T20:00"), first) is False
    assert is_due(at("2026-11-04T22:00"), first) is True


def test_first_puck_drop_is_the_earliest_start() -> None:
    starts = [at("2026-11-04T23:00"), at("2026-11-04T14:00"), at("2026-11-04T19:00")]
    assert first_puck_drop(DAY, starts) == FIRST_PUCK_DROP_2PM


def test_puck_drop_already_passed_makes_the_trigger_due() -> None:
    assert is_due(at("2026-11-04T18:00"), FIRST_PUCK_DROP_2PM) is True


def test_non_utc_time_is_an_error() -> None:
    with pytest.raises(ValueError, match="must be a UTC datetime"):
        next_trigger(datetime(2026, 11, 4, 12, 0))
