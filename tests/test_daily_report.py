"""Tests for the daily prediction report, built from a seeded store."""

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

import pytest
from seeding import add_game, add_team_form, utc

from hockey_model.daily_report import (
    build_report,
    report_json,
    report_markdown,
    report_tag,
    write_report,
)
from hockey_model.game import MissingKind
from hockey_model.game_model.features import GoalieMode
from hockey_model.game_model.logistic import ELO_ONLY
from hockey_model.game_model.nhl_model import NhlGameModel
from hockey_model.types import HockeyModelError

DAY = date(2026, 1, 20)
NOW = utc("2026-01-20T12:00")


def _model(store: sqlite3.Connection) -> NhlGameModel:
    return NhlGameModel(store, ELO_ONLY, GoalieMode.GUESS)


def _seed_form(store: sqlite3.Connection) -> None:
    add_team_form(store, 1, "TOR", 3.5, 2.0)
    add_team_form(store, 2, "BOS", 2.0, 3.0)


def test_report_tag_is_the_utc_day() -> None:
    assert report_tag(DAY) == "reports-2026-01-20"


def test_day_with_no_games_has_no_lines(store: sqlite3.Connection) -> None:
    report = build_report(store, _model(store), DAY, now=NOW)
    assert report.lines == ()
    assert "No games start on this day." in report_markdown(report)
    assert report_json(report)["games"] == []


def test_upcoming_game_is_predicted_with_no_late_run(store: sqlite3.Connection) -> None:
    _seed_form(store)
    add_game(store, 10, "2026-01-20T23:00", "TOR", "BOS", state="FUT")
    report = build_report(store, _model(store), DAY, now=NOW)
    (line,) = report.lines
    assert line.prediction is not None
    assert line.prediction.made_after_start is False
    assert line.prediction.home_win + line.prediction.away_win == pytest.approx(1.0)


def test_game_over_gets_no_prediction(store: sqlite3.Connection) -> None:
    add_game(store, 11, "2026-01-20T01:00", "TOR", "BOS", state="FINAL")
    report = build_report(store, _model(store), DAY, now=NOW)
    (line,) = report.lines
    assert line.prediction is None
    game = report_json(report)["games"][0]
    assert game["home_win"] is None
    assert game["skipped"] == "game is over; no prediction"


def test_in_progress_game_is_not_treated_as_final(store: sqlite3.Connection) -> None:
    _seed_form(store)
    add_game(store, 12, "2026-01-20T11:00", "TOR", "BOS", state="LIVE")
    report = build_report(store, _model(store), DAY, now=NOW)
    (line,) = report.lines
    assert line.prediction is not None


def test_started_game_is_a_late_run_with_inputs_as_of_start(store: sqlite3.Connection) -> None:
    _seed_form(store)
    add_game(store, 13, "2026-01-20T10:00", "TOR", "BOS", state="LIVE")
    report = build_report(store, _model(store), DAY, now=NOW)
    (line,) = report.lines
    assert line.prediction is not None
    assert line.prediction.made_after_start is True
    kinds = {m.kind for m in line.prediction.missing}
    assert MissingKind.LATE_RUN in kinds
    assert "late_run" in report_markdown(report)


def test_naive_now_is_an_error(store: sqlite3.Connection) -> None:
    with pytest.raises(HockeyModelError, match="has no timezone"):
        build_report(store, _model(store), DAY, now=datetime(2026, 1, 20, 12, 0))


def test_write_report_writes_markdown_and_json(store: sqlite3.Connection, tmp_path: Path) -> None:
    report = build_report(store, _model(store), DAY, now=NOW)
    md_path, json_path = write_report(report, tmp_path)
    assert md_path.name == "report-2026-01-20.md"
    assert json_path.name == "report-2026-01-20.json"
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["date"] == "2026-01-20"
    assert md_path.read_text(encoding="utf-8").startswith("# NHL predictions for 2026-01-20")
