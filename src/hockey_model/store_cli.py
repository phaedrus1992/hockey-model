"""CLI commands that work on the SQLite store: refresh, and the model commands."""

import argparse
import os
from collections.abc import Callable
from datetime import UTC, date, datetime

from hockey_model.sources.http import HttpClient
from hockey_model.store.db import connect, db_path_from_env
from hockey_model.store.refresh import RefreshReport, refresh

STORE_COMMANDS = frozenset({"refresh"})


def add_store_commands(add_parser: Callable[..., argparse.ArgumentParser]) -> None:
    """Add the store commands to the CLI parser."""
    parser = add_parser("refresh", help="read every source into the store")
    parser.add_argument(
        "--backfill-from",
        type=date.fromisoformat,
        metavar="YYYY-MM-DD",
        help="read score days from this date; days already read after they ended are skipped",
    )


def _report_json(report: RefreshReport) -> dict[str, object]:
    return {
        "written": report.written,
        "errors": [{"type": type(e).__name__, "message": str(e)} for e in report.errors],
        "notes": list(report.notes),
        "credits": list(report.credits),
    }


def _refresh(args: argparse.Namespace) -> tuple[object, int]:
    conn = connect(db_path_from_env(os.environ))
    try:
        report = refresh(
            conn,
            HttpClient(),
            now=datetime.now(UTC),
            backfill_from=args.backfill_from,
            clock=lambda: datetime.now(UTC),
        )
    finally:
        conn.close()
    return _report_json(report), 1 if report.errors else 0


def run_store_command(args: argparse.Namespace) -> tuple[object, int]:
    """Run a store command. Return the JSON payload and the exit code."""
    return _refresh(args)
