"""Shared fixtures."""

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from hypothesis import settings

from hockey_model.store.db import connect

# A loaded CI or dev machine makes a 200 ms wall-clock deadline fail a test at random.
# The tests check results, not speed.
settings.register_profile("default", deadline=None)
settings.load_profile("default")


@pytest.fixture
def store(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    """An empty store that closes after the test."""
    connection = connect(tmp_path / "store.db")
    yield connection
    connection.close()
