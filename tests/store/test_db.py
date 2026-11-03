"""Tests for the SQLite connection, schema creation, and version guard."""

import sqlite3
from pathlib import Path

import pytest

from hockey_model.store.db import DB_ENV, SCHEMA_VERSION, StoreError, connect, db_path_from_env

EXPECTED_TABLES = {
    "schema_version",
    "source_reads",
    "games",
    "players",
    "skater_games",
    "goalie_games",
    "mp_team_games",
    "mp_goalie_games",
    "starter_reads",
    "injury_reads",
    "model_fits",
}


def _tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {row[0] for row in rows}


@pytest.mark.parametrize("environ", [{}, {DB_ENV: ""}, {DB_ENV: "   "}])
def test_db_path_from_env_unset_or_empty(environ: dict[str, str]) -> None:
    with pytest.raises(StoreError, match=DB_ENV) as info:
        db_path_from_env(environ)
    assert "set" in str(info.value)


def test_db_path_from_env_returns_path() -> None:
    assert db_path_from_env({DB_ENV: "/data/hm.sqlite"}) == Path("/data/hm.sqlite")


def test_connect_creates_schema(tmp_path: Path) -> None:
    conn = connect(tmp_path / "nested" / "hm.sqlite")
    try:
        assert EXPECTED_TABLES <= _tables(conn)
        version = conn.execute("SELECT version FROM schema_version").fetchone()[0]
        assert version == SCHEMA_VERSION == 1
    finally:
        conn.close()


def test_connect_enables_foreign_keys_and_wal(tmp_path: Path) -> None:
    conn = connect(tmp_path / "hm.sqlite")
    try:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        conn.close()


def test_connect_reopens_existing(tmp_path: Path) -> None:
    path = tmp_path / "hm.sqlite"
    first = connect(path)
    first.execute(
        "INSERT INTO source_reads (source, url, fetched_at, ok, error) "
        "VALUES ('nhl', 'https://example.test', '2026-11-03T00:00:00+00:00', 1, NULL)"
    )
    first.commit()
    first.close()

    second = connect(path)
    try:
        count = second.execute("SELECT COUNT(*) FROM source_reads").fetchone()[0]
        assert count == 1
    finally:
        second.close()


def test_connect_rejects_other_version(tmp_path: Path) -> None:
    path = tmp_path / "hm.sqlite"
    setup = connect(path)
    setup.execute("UPDATE schema_version SET version = 99")
    setup.commit()
    setup.close()

    with pytest.raises(StoreError, match="99"):
        connect(path)


def test_db_path_from_env_strips_padding_and_expands_home() -> None:
    assert db_path_from_env({DB_ENV: "  ~/hm.sqlite "}) == Path.home() / "hm.sqlite"


def test_connect_rejects_schema_table_without_version_row(tmp_path: Path) -> None:
    path = tmp_path / "hm.sqlite"
    setup = sqlite3.connect(path)
    setup.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    setup.commit()
    setup.close()

    with pytest.raises(StoreError, match="no row") as info:
        connect(path)
    assert "half-initialized" in str(info.value)


def test_connect_rejects_file_that_is_not_sqlite(tmp_path: Path) -> None:
    path = tmp_path / "hm.sqlite"
    path.write_bytes(b"this is not a database" * 100)

    with pytest.raises(StoreError, match="hm.sqlite") as info:
        connect(path)
    assert "use a new path" in str(info.value)
