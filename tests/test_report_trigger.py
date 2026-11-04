"""Tests for the trigger that decides when the daily report runs."""

from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from hypothesis import given
from hypothesis import strategies as st

from hockey_model.game_day import game_day_window
from hockey_model.report_trigger import (
    REPORT_LEAD,
    TRIGGER_HOURS_UTC,
    TRIGGER_MINUTE_UTC,
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


@pytest.mark.parametrize(
    ("first", "runs_at", "skips_at"),
    [
        # 7 pm EST slate: 00:00 UTC. The old 23:00 slot moves to 22:44.
        ("2026-11-05T00:00", "2026-11-04T22:44", "2026-11-04T21:44"),
        # 7:30 pm EST slate: 00:30 UTC. The old 00:00 slot moves to 23:44.
        ("2026-11-05T00:30", "2026-11-04T23:44", "2026-11-04T22:44"),
        # 2 pm EST matinee: 19:00 UTC. The old 18:00 slot moves to 17:44.
        ("2026-11-04T19:00", "2026-11-04T17:44", "2026-11-04T16:44"),
        # 12:30 pm EST matinee: 17:30 UTC. The old 17:00 slot moves to 16:44.
        ("2026-11-04T17:30", "2026-11-04T16:44", "2026-11-04T15:44"),
        # 8 am EST international game: 13:00 UTC. The old 12:00 slot moves to 11:44.
        ("2026-11-04T13:00", "2026-11-04T11:44", "2026-11-04T00:44"),
    ],
)
def test_each_old_top_of_hour_slot_moves_earlier_to_minute_44(
    first: str, runs_at: str, skips_at: str
) -> None:
    assert is_due(at(runs_at), at(first)) is True
    assert is_due(at(skips_at), at(first)) is False


def test_the_lead_is_the_minutes_left_in_the_hour() -> None:
    assert REPORT_LEAD == timedelta(minutes=60 - TRIGGER_MINUTE_UTC)


def test_a_late_cron_run_keeps_its_own_slot() -> None:
    assert next_trigger(at("2026-11-04T22:50")) == at("2026-11-04T23:44")
    assert is_due(at("2026-11-04T22:50"), at("2026-11-05T00:00")) is True


def test_the_gap_after_the_evening_triggers_reaches_the_next_morning() -> None:
    assert next_trigger(at("2026-11-05T00:44")) == at("2026-11-05T11:44")
    assert next_trigger(at("2026-11-05T11:44")) == at("2026-11-05T15:44")


def test_no_games_runs_at_the_last_trigger_of_the_game_day() -> None:
    first = first_puck_drop(CLOSES, [])
    assert first == at("2026-11-05T05:00")
    assert is_due(at("2026-11-04T23:44"), first) is False
    assert is_due(at("2026-11-05T00:44"), first) is True


def test_first_puck_drop_is_the_earliest_start() -> None:
    starts = [at("2026-11-05T03:00"), at("2026-11-05T00:00"), at("2026-11-05T00:30")]
    assert first_puck_drop(CLOSES, starts) == at("2026-11-05T00:00")


def test_puck_drop_already_passed_makes_the_trigger_due() -> None:
    assert is_due(at("2026-11-05T00:44"), at("2026-11-05T00:00")) is True


def test_trigger_hours_are_sorted_unique_hours_and_the_minute_is_valid() -> None:
    assert list(TRIGGER_HOURS_UTC) == sorted(set(TRIGGER_HOURS_UTC))
    assert all(0 <= hour <= 23 for hour in TRIGGER_HOURS_UTC)
    assert 0 <= TRIGGER_MINUTE_UTC <= 59


def test_non_utc_time_is_an_error() -> None:
    with pytest.raises(HockeyModelError, match="must be a timezone-aware UTC datetime"):
        next_trigger(datetime(2026, 11, 4, 12, 0))


def test_non_utc_offset_is_an_error() -> None:
    eastern = datetime(2026, 11, 4, 12, 0, tzinfo=timezone(timedelta(hours=-5)))
    with pytest.raises(HockeyModelError, match="offset"):
        next_trigger(eastern)


@given(_UTC_TIMES)
def test_next_trigger_is_the_first_trigger_hour_after_now(now: datetime) -> None:
    trigger = next_trigger(now)
    assert trigger > now
    assert trigger.minute == TRIGGER_MINUTE_UTC
    assert trigger.second == trigger.microsecond == 0
    assert trigger.hour in TRIGGER_HOURS_UTC
    slot = now.replace(minute=TRIGGER_MINUTE_UTC, second=0, microsecond=0)
    while slot < trigger:
        assert slot <= now or slot.hour not in TRIGGER_HOURS_UTC
        slot += timedelta(hours=1)


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
def test_is_due_matches_the_lead_comparison_and_is_monotone(now: datetime, start: datetime) -> None:
    assert is_due(now, start) is (next_trigger(now) >= start - REPORT_LEAD)
    if is_due(now, start + timedelta(hours=1)):
        assert is_due(now, start)
