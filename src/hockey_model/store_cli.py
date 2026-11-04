"""CLI commands that work on the SQLite store: refresh, and the model commands."""

import argparse
import os
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path

from hockey_model.backtest.runner import run_backtest, write_game_records
from hockey_model.game import game_win_probability
from hockey_model.game_model.features import ATTEMPT_FEATURES, FEATURES, GoalieMode
from hockey_model.game_model.logistic import ELO_ONLY, fit_logistic
from hockey_model.game_model.nhl_model import NhlGameModel
from hockey_model.game_model.seasons import FIT_FIRST
from hockey_model.game_model.training import game_input, training_rows
from hockey_model.sources.http import HttpClient
from hockey_model.store.db import connect, db_path_from_env
from hockey_model.store.fits import newest_fit, save_fit
from hockey_model.store.reads import game_row
from hockey_model.store.refresh import RefreshReport, refresh
from hockey_model.types import HockeyModelError

STORE_COMMANDS = frozenset({"refresh", "fit", "game", "backtest", "experiments"})
_CANDIDATE_SETS = {"xg": FEATURES, "attempt": ATTEMPT_FEATURES}


def add_store_commands(add_parser: Callable[..., argparse.ArgumentParser]) -> None:
    """Add the store commands to the CLI parser."""
    parser = add_parser("refresh", help="read every source into the store")
    parser.add_argument(
        "--backfill-from",
        type=date.fromisoformat,
        metavar="YYYY-MM-DD",
        help="read score days from this date; days already read after they ended are skipped",
    )
    fit = add_parser("fit", help="fit the game model on the stored games and save the fit")
    fit.add_argument("--through-season", type=int, required=True, metavar="YYYYYYYY")
    fit.add_argument(
        "--features",
        default=",".join(FEATURES),
        help='comma-separated features; "" fits the Elo alone',
    )
    backtest = add_parser("backtest", help="score the model on the stored games")
    backtest.add_argument(
        "--games-out", type=Path, metavar="PATH", help="write one CSV row per predicted game"
    )
    backtest.add_argument(
        "--candidates",
        choices=sorted(_CANDIDATE_SETS),
        default="xg",
        help="xg: the production candidates; attempt: xg_form replaced by attempt_form (#77)",
    )
    game = add_parser("game", help="predict one stored game with the newest fit")
    game.add_argument("game_id", type=int)
    game.add_argument("--level", type=float, default=0.8)
    experiments = add_parser("experiments", help="manage the experiment registry")
    exp_sub = experiments.add_subparsers(dest="experiment_command")
    exp_sub.add_parser("check", help="validate all experiment records")
    exp_run = exp_sub.add_parser(
        "run",
        help="run a backtest for one experiment record",
    )
    exp_run.add_argument("record_id", type=str)


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


def _feature_names(text: str) -> tuple[str, ...]:
    names = tuple(name.strip() for name in text.split(",") if name.strip())
    unknown = [name for name in names if name not in FEATURES]
    if unknown:
        raise HockeyModelError(
            f"fit: unknown feature {unknown[0]!r}; use any of {', '.join(FEATURES)}"
        )
    return names


def _fit(args: argparse.Namespace) -> tuple[object, int]:
    features = _feature_names(args.features)
    conn = connect(db_path_from_env(os.environ))
    try:
        if features:
            rows = training_rows(conn, FIT_FIRST, args.through_season, GoalieMode.ACTUAL)
            if not rows:
                raise HockeyModelError(
                    f"fit through {args.through_season}: no games in the store from {FIT_FIRST}; "
                    "run `hockey-model refresh --backfill-from 2014-10-01`"
                )
            fit = fit_logistic([r.features for r in rows], [r.home_won for r in rows], features)
            games = len(rows)
        else:
            fit, games = ELO_ONLY, 0
        fit_id = save_fit(conn, fit, args.through_season, datetime.now(UTC))
    finally:
        conn.close()
    return {
        "fit_id": fit_id,
        "through_season": args.through_season,
        "games": games,
        **asdict(fit),
    }, 0


def _game(args: argparse.Namespace) -> tuple[object, int]:
    conn = connect(db_path_from_env(os.environ))
    try:
        row = game_row(conn, args.game_id)
        if row is None:
            raise HockeyModelError(
                f"predict game {args.game_id}: the game is not in the store; "
                "run `hockey-model refresh`"
            )
        model = NhlGameModel(conn, newest_fit(conn))
        return game_win_probability(game_input(row), model, level=args.level), 0
    finally:
        conn.close()


def _backtest(args: argparse.Namespace) -> tuple[object, int]:
    conn = connect(db_path_from_env(os.environ))
    try:
        report, records = run_backtest(conn, candidates=_CANDIDATE_SETS[args.candidates])
    finally:
        conn.close()
    if args.games_out is not None:
        write_game_records(args.games_out, records)
    return asdict(report), 0


def _experiments(args: argparse.Namespace) -> tuple[object, int]:
    """Handle the experiments subcommands."""
    command = getattr(args, "experiment_command", None)
    if command == "check":
        from hockey_model.experiments.check import check_all

        result = check_all()
        return result, 0 if result["ok"] else 1
    if command == "run":
        conn = connect(db_path_from_env(os.environ))
        try:
            from hockey_model.experiments.check import run_experiment

            result, _ = run_experiment(
                args.record_id,
                conn,
                FIT_FIRST,
                args.through_season if hasattr(args, "through_season") else 20252026,
                _CANDIDATE_SETS[args.candidates if hasattr(args, "candidates") else "xg"],
            )
            return result, 0 if result.get("ok") else 1
        finally:
            conn.close()
    raise HockeyModelError("experiments: specify check or run")


_HANDLERS = {
    "refresh": _refresh,
    "fit": _fit,
    "game": _game,
    "backtest": _backtest,
    "experiments": _experiments,
}


def run_store_command(args: argparse.Namespace) -> tuple[object, int]:
    """Run a store command. Return the JSON payload and the exit code."""
    return _HANDLERS[args.command](args)
