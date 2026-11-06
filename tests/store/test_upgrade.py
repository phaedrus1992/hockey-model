"""Tests for the store upgrade: a version 1 store moves to the current version, keeping rows."""

import argparse
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from seeding import add_game, add_team_form

from hockey_model.store import upgrade
from hockey_model.store.db import SCHEMA_VERSION, StoreError, connect
from hockey_model.store.reads import mp_attempt_form_before
from hockey_model.store.upgrade import upgrade_store
from hockey_model.store_cli import run_store_command

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "store"
V1_SCHEMA = FIXTURES / "schema_v1.sql"
VIEWS = Path(__file__).resolve().parents[2] / "src" / "hockey_model" / "store" / "views.sql"
V1_MP_ROWS = [
    (2001, "TOR", "2026-01-01", 1.5, 2.5, "2026-01-02T00:00:00Z"),
    (2001, "TOR", "2026-01-01", 1.6, 2.4, "2026-01-03T00:00:00Z"),
    (2002, "BOS", "2026-01-05", 3.1, 0.9, "2026-01-06T00:00:00Z"),
]


def make_v1_store(path: Path) -> Path:
    """Write a version 1 store with duplicate MoneyPuck versions and one saved fit."""
    conn = sqlite3.connect(path)
    conn.executescript(V1_SCHEMA.read_text(encoding="utf-8"))
    conn.execute("INSERT INTO schema_version (version) VALUES (1)")
    conn.executemany("INSERT INTO mp_team_games VALUES (?, ?, ?, ?, ?, ?)", V1_MP_ROWS)
    conn.execute(
        "INSERT INTO model_fits (fit_id, fit_through_season, features, weights, created_at)"
        " VALUES (7, 20252026, '[\"rest\"]', '[0.1]', '2026-11-01T00:00:00Z')"
    )
    conn.commit()
    conn.close()
    return path


def rows(path: Path, sql: str) -> list[tuple]:
    conn = sqlite3.connect(path)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def version_of(path: Path) -> int:
    return rows(path, "SELECT version FROM schema_version")[0][0]


@pytest.fixture
def v1(tmp_path: Path) -> Path:
    return make_v1_store(tmp_path / "store.db")


def test_upgrade_keeps_every_row_and_leaves_attempt_counts_unknown(v1: Path) -> None:
    before = rows(
        v1,
        "SELECT game_id, team, game_date, xg_for, xg_against, fetched_at"
        " FROM mp_team_games ORDER BY game_id, fetched_at",
    )
    report = upgrade_store(v1)
    assert (report.from_version, report.to_version, report.changed) == (1, SCHEMA_VERSION, True)
    after = rows(
        v1,
        "SELECT game_id, team, game_date, xg_for, xg_against, fetched_at"
        " FROM mp_team_games ORDER BY game_id, fetched_at",
    )
    assert after == before
    assert (
        rows(
            v1,
            "SELECT shot_attempts_for, shot_attempts_against, unblocked_for,"
            " unblocked_against FROM mp_team_games",
        )
        == [(None, None, None, None)] * 3
    )
    assert version_of(v1) == SCHEMA_VERSION


def test_upgrade_keeps_fit_ids_and_records_the_run(v1: Path) -> None:
    fit_before = rows(v1, "SELECT * FROM model_fits")
    report = upgrade_store(v1)
    assert rows(v1, "SELECT * FROM model_fits") == fit_before
    ledger = rows(v1, "SELECT from_version, to_version, backup_path FROM schema_migrations")
    assert ledger == [(1, SCHEMA_VERSION, report.backup_path)]


def test_upgrade_writes_a_backup_that_still_reads_as_version_1(v1: Path) -> None:
    report = upgrade_store(v1)
    assert report.backup_path is not None
    backup = Path(report.backup_path)
    assert backup.name == "store.db.v1.bak"
    assert version_of(backup) == 1
    assert len(rows(backup, "SELECT * FROM mp_team_games")) == len(V1_MP_ROWS)


def test_a_second_upgrade_is_a_no_op(v1: Path) -> None:
    upgrade_store(v1)
    report = upgrade_store(v1)
    assert (report.changed, report.backup_path) == (False, None)
    assert len(rows(v1, "SELECT * FROM schema_migrations")) == 1


def test_a_failed_change_rolls_back_and_keeps_version_1(
    v1: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken = (*upgrade.MIGRATIONS[1][:2], "ALTER TABLE no_such_table ADD COLUMN x INTEGER")
    monkeypatch.setitem(upgrade.MIGRATIONS, 1, broken)
    with pytest.raises(StoreError, match="the store is unchanged"):
        upgrade_store(v1)
    assert version_of(v1) == 1
    columns = [row[1] for row in rows(v1, "PRAGMA table_info(mp_team_games)")]
    assert "shot_attempts_for" not in columns
    assert rows(v1, "SELECT COUNT(*) FROM mp_team_games") == [(len(V1_MP_ROWS),)]


def test_an_existing_backup_is_never_overwritten(v1: Path) -> None:
    (v1.parent / "store.db.v1.bak").write_text("keep me", encoding="utf-8")
    with pytest.raises(StoreError, match="already exists"):
        upgrade_store(v1)
    assert (v1.parent / "store.db.v1.bak").read_text(encoding="utf-8") == "keep me"
    assert version_of(v1) == 1


def test_a_missing_file_is_refused_without_being_created(tmp_path: Path) -> None:
    path = tmp_path / "absent.db"
    with pytest.raises(StoreError, match="no store file there"):
        upgrade_store(path)
    assert not path.exists()


def test_a_newer_store_is_refused(v1: Path) -> None:
    conn = sqlite3.connect(v1)
    conn.execute(f"UPDATE schema_version SET version = {SCHEMA_VERSION + 1}")
    conn.commit()
    conn.close()
    with pytest.raises(StoreError, match="no upgrade path"):
        upgrade_store(v1)


def test_the_open_path_refuses_version_1_and_names_the_upgrade(v1: Path) -> None:
    with pytest.raises(StoreError, match="hockey-model store upgrade"):
        connect(v1)
    assert version_of(v1) == 1


def test_the_store_command_runs_the_upgrade_and_prints_the_report(v1: Path) -> None:
    args = argparse.Namespace(command="store", store_command="upgrade", db=str(v1))
    payload, code = run_store_command(args)
    assert code == 0
    assert isinstance(payload, dict)
    assert payload["to_version"] == SCHEMA_VERSION and payload["changed"] is True


def test_the_store_command_needs_a_subcommand(v1: Path) -> None:
    args = argparse.Namespace(command="store", store_command=None, db=str(v1))
    with pytest.raises(StoreError, match="name a subcommand"):
        run_store_command(args)


def test_attempt_form_skips_rows_without_counts(v1: Path) -> None:
    upgrade_store(v1)
    conn = connect(v1)
    add_game(conn, 2001, "2026-01-01T23:00:00Z", "TOR", "BOS")
    add_game(conn, 2002, "2026-01-05T23:00:00Z", "TOR", "BOS")
    add_team_form(conn, 2002, "TOR", 2.0, 2.0, attempts=(55, 45))
    form = mp_attempt_form_before(conn, "TOR", datetime(2026, 2, 1, tzinfo=UTC), 5)
    conn.close()
    assert form == [(55, 45)]
