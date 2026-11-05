"""A score day is complete once a read came after the Eastern game day closed."""

from datetime import UTC, date, datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from hockey_model.game_day import game_day_window
from hockey_model.store.refresh_nhl import DAY_COMPLETE_AFTER_CLOSE, day_is_complete


# 2026-01-10 is EST: the day closes at 05:00 UTC, so the threshold is 12:00 UTC.
# 2026-07-10 is EDT: the day closes at 04:00 UTC, so the threshold is 11:00 UTC.
@pytest.mark.parametrize(
    ("day", "read_at", "complete"),
    [
        (date(2026, 1, 10), datetime(2026, 1, 11, 11, 59, tzinfo=UTC), False),
        (date(2026, 1, 10), datetime(2026, 1, 11, 12, 0, tzinfo=UTC), True),
        (date(2026, 7, 10), datetime(2026, 7, 11, 10, 59, tzinfo=UTC), False),
        (date(2026, 7, 10), datetime(2026, 7, 11, 11, 0, tzinfo=UTC), True),
    ],
)
def test_a_read_is_complete_only_after_the_day_closes_plus_the_margin(
    day: date, read_at: datetime, complete: bool
) -> None:
    assert day_is_complete(day, read_at) is complete


def test_a_day_with_no_read_is_not_complete() -> None:
    assert day_is_complete(date(2026, 1, 10), None) is False


@given(st.dates(date(2026, 1, 1), date(2026, 12, 31)))
def test_every_day_of_the_year_flips_exactly_at_its_own_threshold(day: date) -> None:
    _, closes = game_day_window(day)
    threshold = closes + DAY_COMPLETE_AFTER_CLOSE
    assert day_is_complete(day, threshold) is True
    assert day_is_complete(day, threshold - timedelta(minutes=1)) is False
