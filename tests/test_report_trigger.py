"""Tests for the trigger that decides when the daily report runs."""

from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from hypothesis import given
from hypothesis import strategies as st

from hockey_model.game_day import game_day_window
from hockey_model.report_trigger import (
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
        # 7 pm EST slate: 00:00 UTC. The 23:37 trigger runs it.
        ("2026-11-05T00:00", "2026-11-04T23:37", "2026-11-04T22:37"),
        # 7:30 pm EST slate: 00:30 UTC. The 23:37 trigger runs it too.
        ("2026-11-05T00:30", "2026-11-04T23:37", "2026-11-04T22:37"),
        # 2 pm EST matinee: 19:00 UTC. The 18:37 trigger runs it.
        ("2026-11-04T19:00", "2026-11-04T18:37", "2026-11-04T17:37"),
        # 12:30 pm EST matinee: 17:30 UTC. The 16:37 trigger runs it.
        ("2026-11-04T17:30", "2026-11-04T16:37", "2026-11-04T15:37"),
        # 8 am EST international game: 13:00 UTC. The 12:37 trigger runs it.
        ("2026-11-04T13:00", "2026-11-04T12:37", "2026-11-04T01:37"),
    ],
)
def test_the_last_trigger_before_the_first_puck_drop_runs(
    first: str, runs_at: str, skips_at: str
) -> None:
    assert is_due(at(runs_at), at(first)) is True
    assert is_due(at(skips_at), at(first)) is False


def test_a_late_cron_run_keeps_its_own_slot() -> None:
    assert next_trigger(at("2026-11-04T23:50")) == at("2026-11-05T00:37")
    assert is_due(at("2026-11-04T23:50"), at("2026-11-05T00:30")) is True


def test_the_gap_after_the_evening_triggers_reaches_the_next_morning() -> None:
    assert next_trigger(at("2026-11-05T01:37")) == at("2026-11-05T12:37")
    assert next_trigger(at("2026-11-05T12:37")) == at("2026-11-05T15:37")


def test_no_games_waits_for_the_last_trigger_of_the_game_day() -> None:
    first = first_puck_drop(CLOSES, [])
    assert first == at("2026-11-05T05:00")
    assert is_due(at("2026-11-05T00:37"), first) is False
    assert is_due(at("2026-11-05T01:37"), first) is True


def test_first_puck_drop_is_the_earliest_start() -> None:
    starts = [at("2026-11-05T03:00"), at("2026-11-05T00:00"), at("2026-11-05T00:30")]
    assert first_puck_drop(CLOSES, starts) == at("2026-11-05T00:00")


def test_puck_drop_already_passed_makes_the_trigger_due() -> None:
    assert is_due(at("2026-11-05T01:37"), at("2026-11-05T00:00")) is True


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
def test_is_due_matches_the_slot_comparison_and_is_monotone(now: datetime, start: datetime) -> None:
    assert is_due(now, start) is (next_trigger(now) >= start)
    if is_due(now, start + timedelta(hours=1)):
        assert is_due(now, start)
