"""Tests for the Eastern game day."""

from datetime import UTC, date, datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from hockey_model.game_day import GAME_TIME_ZONE, game_day_of, game_day_window
from hockey_model.types import HockeyModelError


def at(text: str) -> datetime:
    """Parse ``2026-11-05T00:30`` as UTC."""
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def test_evening_slate_after_utc_midnight_stays_on_its_eastern_day() -> None:
    # A 7:30 pm EST puck drop is 00:30 UTC on the next UTC date.
    assert game_day_of(at("2026-11-05T00:30")) == date(2026, 11, 4)


def test_winter_window_is_eastern_standard_time() -> None:
    assert game_day_window(date(2026, 11, 4)) == (at("2026-11-04T05:00"), at("2026-11-05T05:00"))


def test_summer_window_is_eastern_daylight_time() -> None:
    assert game_day_window(date(2026, 10, 10)) == (at("2026-10-10T04:00"), at("2026-10-11T04:00"))


@pytest.mark.parametrize(
    ("day", "hours"),
    [(date(2026, 3, 8), 23), (date(2026, 11, 1), 25), (date(2026, 11, 4), 24)],
)
def test_daylight_saving_days_have_their_real_length(day: date, hours: int) -> None:
    opens, closes = game_day_window(day)
    assert closes - opens == timedelta(hours=hours)


def test_naive_time_is_an_error() -> None:
    with pytest.raises(HockeyModelError, match="has no timezone"):
        game_day_of(datetime(2026, 11, 4, 19, 0))


@given(st.dates(min_value=date(2000, 1, 1), max_value=date(2099, 12, 30)))
def test_window_holds_exactly_the_moments_of_its_day(day: date) -> None:
    opens, closes = game_day_window(day)
    assert opens.tzinfo is UTC and closes.tzinfo is UTC
    assert opens.astimezone(GAME_TIME_ZONE).time().hour == 0
    assert game_day_of(opens) == day
    assert game_day_of(closes - timedelta(microseconds=1)) == day
    assert game_day_of(closes) == day + timedelta(days=1)
