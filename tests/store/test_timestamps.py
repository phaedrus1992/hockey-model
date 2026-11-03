"""Tests for the store time text."""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from hypothesis import given
from hypothesis import strategies as st

from hockey_model.store.timestamps import iso_utc, parse_iso_utc
from hockey_model.types import HockeyModelError


@given(st.datetimes(timezones=st.timezones() | st.just(UTC)))
def test_parse_reverses_iso_utc(moment: datetime) -> None:
    assert parse_iso_utc(iso_utc(moment)) == moment


@given(st.datetimes(timezones=st.just(UTC)))
def test_iso_utc_text_sorts_like_time(moment: datetime) -> None:
    later = moment + timedelta(microseconds=1) if moment.year < 9999 else moment
    assert iso_utc(moment) <= iso_utc(later)


def test_iso_utc_writes_microseconds_and_an_offset() -> None:
    zone = timezone(timedelta(hours=-5))
    assert iso_utc(datetime(2026, 1, 1, 12, 0, tzinfo=zone)) == "2026-01-01T17:00:00.000000+00:00"


def test_iso_utc_rejects_a_naive_time() -> None:
    with pytest.raises(HockeyModelError, match="no timezone"):
        iso_utc(datetime(2026, 1, 1))


def test_parse_iso_utc_rejects_a_naive_text() -> None:
    with pytest.raises(HockeyModelError, match="no timezone"):
        parse_iso_utc("2026-01-01T12:00:00")
