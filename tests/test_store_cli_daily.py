"""Tests for the `report-due` and `daily` store commands."""

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from hockey_model import store_cli
from hockey_model.cli import main
from hockey_model.game_model.seasons import season_of
from hockey_model.sources.nhl import GameRow


def _row(game_id: int, start: str) -> GameRow:
    when = datetime.fromisoformat(start).replace(tzinfo=UTC)
    return GameRow(game_id, 20262027, 2, when, "TOR", "BOS", "FUT", None, None, None)


def test_report_due_prints_the_schedule_and_the_tag(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rows = [_row(1, "2026-11-04T19:00"), _row(2, "2026-11-04T14:00")]
    monkeypatch.setattr(store_cli, "fetch_score_day", lambda client, day: rows)
    assert main(["report-due", "--date", "2026-11-04", "--force"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["tag"] == "reports-2026-11-04"
    assert payload["first_puck_drop_utc"] == "2026-11-04T14:00:00.000000+00:00"
    assert payload["forced"] is True
    assert payload["due"] is True


def test_report_due_without_games_uses_the_end_of_the_day(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(store_cli, "fetch_score_day", lambda client, day: [])
    assert main(["report-due", "--date", "2026-11-04"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["first_puck_drop_utc"] == "2026-11-05T00:00:00.000000+00:00"
    assert payload["forced"] is False


@pytest.mark.parametrize(
    ("day", "season"),
    [
        (date(2026, 11, 4), 20262027),
        (date(2027, 1, 9), 20262027),
        (date(2026, 7, 1), 20262027),
        (date(2026, 6, 30), 20252026),
        (date(2026, 9, 25), 20262027),
    ],
)
def test_season_of_names_the_season_that_holds_the_day(day: date, season: int) -> None:
    assert season_of(day) == season


def test_daily_refuses_a_day_with_no_model_fit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("HOCKEY_MODEL_DB", str(tmp_path / "store.db"))
    assert main(["daily", "--date", "2026-11-04", "--out-dir", str(tmp_path)]) == 2
    assert "error:" in capsys.readouterr().err
