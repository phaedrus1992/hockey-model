"""Tests for the windows of a backfill."""

from datetime import date, timedelta

from hypothesis import given
from hypothesis import strategies as st

from hockey_model.store.refresh_backfill import WINDOW_DAYS, windows


def test_windows_start_at_the_newest_day_and_walk_back() -> None:
    found = list(windows(date(2020, 1, 1), date(2022, 6, 1)))
    assert found[0][1] == date(2022, 6, 1)
    assert found[-1][0] == date(2020, 1, 1)
    assert len(found) == 3


def test_windows_of_a_short_span_are_one_window() -> None:
    assert list(windows(date(2026, 1, 1), date(2026, 1, 10))) == [
        (date(2026, 1, 1), date(2026, 1, 10))
    ]


def test_windows_of_an_empty_span_are_none() -> None:
    assert list(windows(date(2026, 1, 10), date(2026, 1, 1))) == []


@given(
    first=st.dates(min_value=date(2014, 10, 1), max_value=date(2030, 1, 1)),
    days=st.integers(min_value=0, max_value=4000),
)
def test_property_windows_cover_every_day_once_newest_first(first: date, days: int) -> None:
    last = first + timedelta(days=days)
    found = list(windows(first, last))
    covered = [
        start + timedelta(days=n) for start, end in found for n in range((end - start).days + 1)
    ]
    assert sorted(covered) == [first + timedelta(days=n) for n in range(days + 1)]
    assert all((end - start).days < WINDOW_DAYS for start, end in found)
    assert [end for _, end in found] == sorted((end for _, end in found), reverse=True)
