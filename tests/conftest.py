"""Shared fixtures."""

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from hockey_model.store.db import connect


@pytest.fixture
def store(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    """An empty store that closes after the test."""
    connection = connect(tmp_path / "store.db")
    yield connection
    connection.close()
