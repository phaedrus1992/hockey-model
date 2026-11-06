"""Upgrade a store file to the current schema version, keeping every row.

Only this producer step migrates a store. The open path in ``store/db.py`` validates the
version and never changes the file. The upgrade takes a SQLite backup first, applies the
ordered changes in one transaction, and records each run in ``schema_migrations``.

A version 1 store gets NULL in the four MoneyPuck attempt columns. Those rows predate the
counts, so the value is unknown, and no code fills it in.
"""

import argparse
import sqlite3
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from hockey_model.store.db import SCHEMA_VERSION, StoreError
from hockey_model.store.timestamps import iso_utc

# The change from each version to the next, in order. Each change is one statement.
MIGRATIONS: dict[int, tuple[str, ...]] = {
    1: (
        "ALTER TABLE mp_team_games ADD COLUMN shot_attempts_for INTEGER",
        "ALTER TABLE mp_team_games ADD COLUMN shot_attempts_against INTEGER",
        "ALTER TABLE mp_team_games ADD COLUMN unblocked_for INTEGER",
        "ALTER TABLE mp_team_games ADD COLUMN unblocked_against INTEGER",
    ),
}
_LEDGER = (
    "CREATE TABLE IF NOT EXISTS schema_migrations ("
    " from_version INTEGER NOT NULL, to_version INTEGER NOT NULL,"
    " applied_at TEXT NOT NULL, backup_path TEXT NOT NULL)"
)
_VIEWS_PATH = Path(__file__).with_name("views.sql")


@dataclass(frozen=True)
class UpgradeReport:
    """The outcome of one upgrade run. ``backup_path`` is None when nothing changed."""

    path: str
    from_version: int
    to_version: int
    changed: bool
    backup_path: str | None


def _read_version(conn: sqlite3.Connection, path: Path) -> int:
    """Return the stored version. Refuse a file that has no version row."""
    try:
        row = conn.execute("SELECT version FROM schema_version").fetchone()
    except sqlite3.Error as exc:
        raise StoreError(
            f"upgrade store {str(path)!r}: no schema_version table ({exc}); "
            "it is not a hockey-model store, so check the path"
        ) from exc
    if row is None:
        raise StoreError(
            f"upgrade store {str(path)!r}: schema_version has no row, so the store is "
            "half-initialized and cannot be upgraded; restore it from a backup or use a new path"
        )
    return int(row[0])


def _check_path(path: Path) -> None:
    """Refuse a missing file. ``sqlite3.connect`` would create an empty one."""
    if not path.is_file():
        raise StoreError(
            f"upgrade store {str(path)!r}: no store file there; check the path given to --db "
            "or HOCKEY_MODEL_DB"
        )


def _backup(conn: sqlite3.Connection, path: Path, version: int) -> Path:
    """Write a consistent copy with SQLite's backup API. Refuse to overwrite an old copy."""
    target = path.with_name(f"{path.name}.v{version}.bak")
    if target.exists():
        raise StoreError(
            f"upgrade store {str(path)!r}: backup {str(target)!r} already exists; move it aside "
            "so the earlier backup is kept, then run the upgrade again"
        )
    dest = sqlite3.connect(target)
    try:
        conn.backup(dest)
    finally:
        dest.close()
    return target


def _apply(conn: sqlite3.Connection, path: Path, stored: int, backup: Path) -> None:
    """Run the changes and the ledger row in one transaction. Roll back on any error."""
    statements = [s for v in range(stored, SCHEMA_VERSION) for s in MIGRATIONS[v]]
    conn.execute("BEGIN IMMEDIATE")
    try:
        for statement in statements:
            conn.execute(statement)
        conn.execute(_LEDGER)
        conn.execute(
            "INSERT INTO schema_migrations (from_version, to_version, applied_at, backup_path)"
            " VALUES (?, ?, ?, ?)",
            (stored, SCHEMA_VERSION, iso_utc(datetime.now(UTC)), str(backup)),
        )
        conn.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))
        conn.execute("COMMIT")
    except sqlite3.Error as exc:
        conn.execute("ROLLBACK")
        raise StoreError(
            f"upgrade store {str(path)!r}: {exc}; the store is unchanged. The backup is "
            f"{str(backup)!r}. Fix the cause, then run the upgrade again."
        ) from exc


def upgrade_store(path: Path) -> UpgradeReport:
    """Upgrade the store at ``path`` to ``SCHEMA_VERSION``. Return what it did."""
    _check_path(path)
    conn = sqlite3.connect(path, isolation_level=None)
    try:
        stored = _read_version(conn, path)
        if stored == SCHEMA_VERSION:
            return UpgradeReport(str(path), stored, SCHEMA_VERSION, False, None)
        if stored > SCHEMA_VERSION or stored not in MIGRATIONS:
            raise StoreError(
                f"upgrade store {str(path)!r}: no upgrade path from version {stored} to "
                f"{SCHEMA_VERSION}; use a hockey-model that reads version {stored}, or a new path"
            )
        backup = _backup(conn, path, stored)
        _apply(conn, path, stored, backup)
    finally:
        conn.close()
    # Views are code. Rebuild them after the commit, as every connection does.
    rebuilt = sqlite3.connect(path)
    try:
        rebuilt.executescript(_VIEWS_PATH.read_text(encoding="utf-8"))
    finally:
        rebuilt.close()
    return UpgradeReport(str(path), stored, SCHEMA_VERSION, True, str(backup))


def add_store_group(add_parser: Callable[..., argparse.ArgumentParser]) -> None:
    """Add the ``store`` command group with its ``upgrade`` subcommand."""
    group = add_parser("store", help="manage the store file")
    sub = group.add_subparsers(dest="store_command")
    upgrade = sub.add_parser(
        "upgrade", help="move the store to the current schema, keeping every row"
    )
    upgrade.add_argument(
        "--db",
        default=None,
        metavar="PATH",
        help="store file to upgrade; default is HOCKEY_MODEL_DB",
    )


def run_store_group(args: argparse.Namespace, db_path: Path) -> tuple[object, int]:
    """Run a ``store`` subcommand and return its JSON payload and exit code."""
    if args.store_command != "upgrade":
        raise StoreError("store: name a subcommand, such as `hockey-model store upgrade`")
    return asdict(upgrade_store(db_path)), 0
