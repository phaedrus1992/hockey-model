"""Daily prediction report: every game that starts on one UTC day, as Markdown and JSON.

A game that started before the run is still predicted. Its inputs are taken as of the game
start, and the report marks it as a late run. A game that is over or postponed gets no
prediction.
"""

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from hockey_model.game import GamePrediction, MissingInput, game_win_probability
from hockey_model.game_model.training import game_input
from hockey_model.models import GameModel
from hockey_model.sources.nhl import FINAL_STATES, GameRow
from hockey_model.store.reads import games_on_day
from hockey_model.store.timestamps import iso_utc
from hockey_model.utc import require_utc

# A postponed game has no result and no puck drop yet, so it gets no prediction.
NO_PREDICTION_STATES = FINAL_STATES | {"PPD"}


@dataclass(frozen=True, slots=True)
class DailyLine:
    """One game in the daily report. ``prediction`` is None when no prediction was made."""

    row: GameRow
    prediction: GamePrediction | None
    skipped: str


@dataclass(frozen=True, slots=True)
class DailyReport:
    """The games of one UTC day, with their predictions and the time the run made them."""

    day: date
    generated_at: datetime
    level: float
    lines: tuple[DailyLine, ...]


def report_tag(day: date) -> str:
    """Return the release tag for the report of ``day``, such as ``reports-2026-11-04``."""
    return f"reports-{day.isoformat()}"


def _predict_line(row: GameRow, model: GameModel, now: datetime, level: float) -> DailyLine:
    if row.state in NO_PREDICTION_STATES:
        return DailyLine(row, None, f"game is over or postponed (state {row.state}); no prediction")
    # A late run uses the inputs known at puck drop, so the note in the report is true.
    as_of = min(now, row.start)
    prediction = game_win_probability(game_input(row), model, as_of=as_of, level=level)
    return DailyLine(row, prediction, "")


def build_report(
    conn: sqlite3.Connection,
    model: GameModel,
    day: date,
    *,
    now: datetime,
    level: float = 0.8,
) -> DailyReport:
    """Predict every game that starts on ``day``. Raise on the first game that fails."""
    require_utc(now, "daily report now")
    lines = tuple(_predict_line(row, model, now, level) for row in games_on_day(conn, day))
    return DailyReport(day, now.astimezone(UTC), level, lines)


def _credits(report: DailyReport) -> list[str]:
    return sorted({c for line in report.lines if line.prediction for c in line.prediction.credits})


def _missing_json(missing: tuple[MissingInput, ...]) -> list[dict[str, Any]]:
    return [{"kind": m.kind.value, "team": m.team, "note": m.note} for m in missing]


def _line_json(line: DailyLine) -> dict[str, Any]:
    row = line.row
    base: dict[str, Any] = {
        "game_id": row.game_id,
        "away": row.away,
        "home": row.home,
        "start_utc": iso_utc(row.start),
        "state": row.state,
        "skipped": line.skipped or None,
    }
    prediction = line.prediction
    if prediction is None:
        return {
            **base,
            "home_win": None,
            "away_win": None,
            "made_after_start": False,
            "missing": [],
        }
    return {
        **base,
        "home_win": prediction.home_win,
        "away_win": prediction.away_win,
        "made_after_start": prediction.made_after_start,
        "missing": _missing_json(prediction.missing),
    }


def report_json(report: DailyReport) -> dict[str, Any]:
    """Return the JSON copy of the report. Every game has the same keys."""
    return {
        "date": report.day.isoformat(),
        "generated_at": iso_utc(report.generated_at),
        "level": report.level,
        "games": [_line_json(line) for line in report.lines],
        "credits": _credits(report),
    }


def _percent(value: float | None) -> str:
    return "-" if value is None else f"{value:.1%}"


def _cell(text: str) -> str:
    """Make one value safe inside a Markdown table cell. The value comes from a remote feed."""
    return " ".join(text.replace("|", "\\|").split())


def _notes(line: DailyLine) -> str:
    if line.skipped:
        return _cell(line.skipped)
    prediction = line.prediction
    if prediction is None:
        return ""
    notes = [f"{m.kind.value}: {m.note}" for m in prediction.missing]
    return _cell("; ".join(notes) or "none")


def report_markdown(report: DailyReport) -> str:
    """Return the Markdown copy of the report, one table row per game."""
    out = [
        f"# NHL predictions for {report.day.isoformat()}",
        "",
        f"Generated {iso_utc(report.generated_at)}. Interval level {report.level:.0%}.",
        "",
    ]
    if not report.lines:
        out.append("No games start on this day.")
    else:
        out.append("| Game | Start (UTC) | State | Home win | Away win | Notes |")
        out.append("| --- | --- | --- | --- | --- | --- |")
        for line in report.lines:
            row = line.row
            p = line.prediction
            out.append(
                f"| {_cell(f'{row.away} at {row.home}')} ({row.game_id}) | {iso_utc(row.start)}"
                f" | {_cell(row.state)}"
                f" | {_percent(p.home_win if p else None)}"
                f" | {_percent(p.away_win if p else None)} | {_notes(line)} |"
            )
    out.append("")
    credits = _credits(report)
    if credits:
        out.append("Sources: " + " ".join(credits))
        out.append("")
    return "\n".join(out)


def write_report(report: DailyReport, out_dir: Path) -> tuple[Path, Path]:
    """Write the Markdown and JSON copies. Return their paths, Markdown first.

    Both strings are built before either file is written, so a failed build writes nothing.
    """
    markdown = report_markdown(report)
    payload = json.dumps(report_json(report), indent=2, sort_keys=True) + "\n"
    stem = f"report-{report.day.isoformat()}"
    md_path = out_dir / f"{stem}.md"
    json_path = out_dir / f"{stem}.json"
    md_path.write_text(markdown, encoding="utf-8")
    json_path.write_text(payload, encoding="utf-8")
    return md_path, json_path
