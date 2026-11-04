"""Tests for the trigger that decides when the daily report runs."""

from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from hypothesis import given
from hypothesis import strategies as st

from hockey_model.game_day import game_day_window
from hockey_model.report_trigger import (
    TRIGGER_INTERVAL_HOURS,
    first_puck_drop,
    is_due,
    next_trigger,
)
from hockey_model.types import HockeyModelError

_UTC_TIMES = st.datetimes(
    min_value=datetime(2000, 1, 1),
    max_value=datetime(2099, 12, 31, 23, 59),
    timezones=st.just(UTC),
)
_DAYS = st.dates(min_value=date(2000, 1, 1), max_value=date(2099, 12, 30))


def at(text: str) -> datetime:
    """Parse ``2026-11-04T12:30`` as UTC."""
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


DAY = date(2026, 11, 4)
CLOSES = game_day_window(DAY)[1]
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


def test_no_games_waits_for_the_last_trigger_of_the_game_day() -> None:
    first = first_puck_drop(CLOSES, [])
    assert first == at("2026-11-05T05:00")
    assert is_due(at("2026-11-05T02:00"), first) is False
    assert is_due(at("2026-11-05T04:00"), first) is True


def test_first_puck_drop_is_the_earliest_start() -> None:
    starts = [at("2026-11-04T23:00"), at("2026-11-04T14:00"), at("2026-11-04T19:00")]
    assert first_puck_drop(CLOSES, starts) == FIRST_PUCK_DROP_2PM


def test_puck_drop_already_passed_makes_the_trigger_due() -> None:
    assert is_due(at("2026-11-04T18:00"), FIRST_PUCK_DROP_2PM) is True


def test_non_utc_time_is_an_error() -> None:
    with pytest.raises(HockeyModelError, match="must be a timezone-aware UTC datetime"):
        next_trigger(datetime(2026, 11, 4, 12, 0))


def test_non_utc_offset_is_an_error() -> None:
    eastern = datetime(2026, 11, 4, 12, 0, tzinfo=timezone(timedelta(hours=-5)))
    with pytest.raises(HockeyModelError, match="offset"):
        next_trigger(eastern)


@given(_UTC_TIMES)
def test_next_trigger_is_the_next_slot_boundary(now: datetime) -> None:
    trigger = next_trigger(now)
    assert trigger > now
    assert trigger.minute == trigger.second == trigger.microsecond == 0
    assert trigger.hour % TRIGGER_INTERVAL_HOURS == 0
    assert trigger - now <= timedelta(hours=TRIGGER_INTERVAL_HOURS)


@given(_DAYS, st.lists(_UTC_TIMES, max_size=8))
def test_first_puck_drop_is_the_minimum_or_the_day_close(day: date, starts: list[datetime]) -> None:
    closes = game_day_window(day)[1]
    result = first_puck_drop(closes, starts)
    if starts:
        assert result in starts
        assert all(result <= start for start in starts)
    else:
        assert result == closes


@given(_UTC_TIMES, _UTC_TIMES)
def test_is_due_matches_the_slot_comparison_and_is_monotone(now: datetime, start: datetime) -> None:
    assert is_due(now, start) is (next_trigger(now) >= start)
    if is_due(now, start + timedelta(hours=1)):
        assert is_due(now, start)
