"""Tests for ``abandoned_urls``, the rule that names a known gap."""

import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from itertools import takewhile
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from hockey_model.store.db import connect
from hockey_model.store.source_reads import ABANDON_AFTER_FAILED_READS, abandoned_urls, record_read

START = datetime(2026, 1, 1, tzinfo=UTC)
SOURCE = "nhl_scores"


def _record(conn: sqlite3.Connection, url: str, outcomes: list[bool]) -> None:
    for step, ok in enumerate(outcomes):
        record_read(conn, SOURCE, url, START + timedelta(hours=step), None if ok else "HTTP 500")


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(tmp_path / "store.db")
    yield connection
    connection.close()


@settings(max_examples=20)
@given(outcomes=st.lists(st.booleans(), max_size=12))
def test_property_a_url_is_abandoned_after_enough_failures_since_its_last_good_read(
    outcomes: list[bool], tmp_path_factory: pytest.TempPathFactory
) -> None:
    connection = connect(tmp_path_factory.mktemp("store") / "store.db")
    _record(connection, "u", outcomes)
    trailing_failures = len(list(takewhile(lambda ok: not ok, reversed(outcomes))))
    expected = trailing_failures >= ABANDON_AFTER_FAILED_READS
    assert ("u" in abandoned_urls(connection, SOURCE)) == expected
    connection.close()


def test_a_good_read_clears_the_failures_before_it(conn: sqlite3.Connection) -> None:
    _record(conn, "u", [False, False, True, False])
    assert abandoned_urls(conn, SOURCE) == frozenset()


def test_another_source_does_not_abandon_the_url(conn: sqlite3.Connection) -> None:
    _record(conn, "u", [False, False])
    assert abandoned_urls(conn, "nhl_boxscores") == frozenset()
