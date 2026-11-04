"""CLI commands that work on the SQLite store: refresh, and the model commands."""

import argparse
import os
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path

from hockey_model.backtest.runner import run_backtest, write_game_records
from hockey_model.daily_report import build_report, report_tag, write_report
from hockey_model.game import game_win_probability
from hockey_model.game_day import game_day_of, game_day_window
from hockey_model.game_model.features import ATTEMPT_FEATURES, FEATURES, GoalieMode
from hockey_model.game_model.logistic import ELO_ONLY, fit_logistic
from hockey_model.game_model.nhl_model import NhlGameModel
from hockey_model.game_model.seasons import FIT_FIRST
from hockey_model.game_model.training import game_input, training_rows
from hockey_model.report_trigger import first_puck_drop, is_due
from hockey_model.sources.http import HttpClient
from hockey_model.sources.nhl import GameRow, fetch_score_day
from hockey_model.store.db import connect, db_path_from_env
from hockey_model.store.fits import newest_fit, save_fit
from hockey_model.store.reads import game_row
from hockey_model.store.refresh import RefreshReport, refresh, refresh_starters
from hockey_model.store.refresh_other import current_season_start
from hockey_model.store.timestamps import iso_utc
from hockey_model.types import HockeyModelError

STORE_COMMANDS = frozenset({"refresh", "fit", "game", "backtest", "daily", "report-due"})
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
    parser.add_argument(
        "--starters-only",
        action="store_true",
        help="read only the schedule, the goalie sources, and the injuries",
    )
    fit = add_parser("fit", help="fit the game model on the stored games and save the fit")
    fit.add_argument(
        "--through-season",
        type=int,
        default=None,
        metavar="YYYYYYYY",
        help="last season in the fit; default is the season that holds today (UTC)",
    )
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
    daily = add_parser("daily", help="predict every game of one UTC day; write Markdown and JSON")
    daily.add_argument(
        "--date",
        type=date.fromisoformat,
        default=None,
        metavar="YYYY-MM-DD",
        help="Eastern game day to predict; default is the game day that holds now",
    )
    daily.add_argument("--out-dir", type=Path, required=True, metavar="DIR")
    daily.add_argument("--level", type=float, default=0.8)
    due = add_parser("report-due", help="say whether this trigger publishes the daily report")
    due.add_argument(
        "--date",
        type=date.fromisoformat,
        default=None,
        metavar="YYYY-MM-DD",
        help="Eastern game day to check; default is the game day that holds now",
    )
    due.add_argument("--force", action="store_true", help="publish even outside the trigger")


def _report_json(report: RefreshReport) -> dict[str, object]:
    return {
        "written": report.written,
        "errors": [{"type": type(e).__name__, "message": str(e)} for e in report.errors],
        "notes": list(report.notes),
        "credits": list(report.credits),
    }


def _refresh(args: argparse.Namespace) -> tuple[object, int]:
    if args.starters_only and args.backfill_from is not None:
        raise HockeyModelError("refresh: a backfill reads every source; drop --starters-only")
    conn = connect(db_path_from_env(os.environ))
    try:
        if args.starters_only:
            report = refresh_starters(
                conn, HttpClient(), now=datetime.now(UTC), clock=lambda: datetime.now(UTC)
            )
        else:
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
    through = args.through_season
    if through is None:
        through = _season_code(datetime.now(UTC))
    conn = connect(db_path_from_env(os.environ))
    try:
        if features:
            rows = training_rows(conn, FIT_FIRST, through, GoalieMode.ACTUAL)
            if not rows:
                raise HockeyModelError(
                    f"fit through {through}: no games in the store from {FIT_FIRST}; "
                    "run `hockey-model refresh --backfill-from 2014-10-01`"
                )
            fit = fit_logistic([r.features for r in rows], [r.home_won for r in rows], features)
            games = len(rows)
        else:
            fit, games = ELO_ONLY, 0
        fit_id = save_fit(conn, fit, through, datetime.now(UTC))
    finally:
        conn.close()
    return {
        "fit_id": fit_id,
        "through_season": through,
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


def _daily(args: argparse.Namespace) -> tuple[object, int]:
    now = datetime.now(UTC)
    day = args.date if args.date is not None else game_day_of(now)
    conn = connect(db_path_from_env(os.environ))
    try:
        model = NhlGameModel(conn, newest_fit(conn))
        report = build_report(conn, model, day, now=now, level=args.level)
    finally:
        conn.close()
    md_path, json_path = write_report(report, args.out_dir)
    return {
        "date": day.isoformat(),
        "games": len(report.lines),
        "files": [str(md_path), str(json_path)],
    }, 0


def _game_day_games(day: date, closes: datetime) -> list[GameRow]:
    """Return the games of the Eastern game ``day`` from its score feed.

    The feed already groups games by Eastern date. The window check keeps a game whose
    start the feed lists under the wrong date out of the report.
    """
    opens = game_day_window(day)[0]
    return [game for game in fetch_score_day(HttpClient(), day) if opens <= game.start < closes]


def _report_due(args: argparse.Namespace) -> tuple[object, int]:
    now = datetime.now(UTC)
    day = args.date if args.date is not None else game_day_of(now)
    closes = game_day_window(day)[1]
    games = _game_day_games(day, closes)
    first = first_puck_drop(closes, [game.start for game in games])
    return {
        "date": day.isoformat(),
        "tag": report_tag(day),
        "games": len(games),
        "first_puck_drop_utc": iso_utc(first),
        "due": args.force or is_due(now, first),
    }, 0


def _season_code(now: datetime) -> int:
    """Return the season code, such as 20262027, of the season that holds ``now``."""
    start = current_season_start(now)
    return start * 10000 + start + 1


def _backtest(args: argparse.Namespace) -> tuple[object, int]:
    conn = connect(db_path_from_env(os.environ))
    try:
        report, records = run_backtest(conn, candidates=_CANDIDATE_SETS[args.candidates])
    finally:
        conn.close()
    if args.games_out is not None:
        write_game_records(args.games_out, records)
    return asdict(report), 0


_HANDLERS = {
    "refresh": _refresh,
    "fit": _fit,
    "game": _game,
    "backtest": _backtest,
    "daily": _daily,
    "report-due": _report_due,
}


def run_store_command(args: argparse.Namespace) -> tuple[object, int]:
    """Run a store command. Return the JSON payload and the exit code."""
    return _HANDLERS[args.command](args)
