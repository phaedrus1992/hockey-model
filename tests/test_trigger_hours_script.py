"""Tests for scripts/trigger_hours.py, which derives the report trigger hours."""

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest
from hypothesis import given
from hypothesis import strategies as st

from hockey_model.report_trigger import TRIGGER_MINUTE_UTC, is_due

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "trigger_hours.py"
if not SCRIPT.exists():
    # A mutation run copies src/ and tests/ only, so the script is absent there.
    pytest.skip("scripts/trigger_hours.py is not copied", allow_module_level=True)


def _load() -> ModuleType:
    """Import the script by path, because scripts/ is not a package."""
    spec = importlib.util.spec_from_file_location("trigger_hours", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HOURS = _load()


def _week(*games: tuple[str, str, int]) -> dict[str, object]:
    days: dict[str, list[dict[str, object]]] = {}
    for day, start, game_type in games:
        days.setdefault(day, []).append({"startTimeUTC": start, "gameType": game_type})
    return {"gameWeek": [{"date": day, "games": rows} for day, rows in days.items()]}


def test_first_starts_takes_the_earliest_game_of_each_game_day() -> None:
    week = _week(
        ("2026-11-04", "2026-11-05T03:00:00Z", 2),
        ("2026-11-04", "2026-11-05T00:00:00Z", 2),
        ("2026-11-05", "2026-11-05T17:00:00Z", 2),
    )
    firsts = HOURS.first_starts([week], {2})
    assert firsts == {
        "2026-11-04": datetime(2026, 11, 5, 0, 0, tzinfo=UTC),
        "2026-11-05": datetime(2026, 11, 5, 17, 0, tzinfo=UTC),
    }


def test_first_starts_skips_other_game_types() -> None:
    week = _week(
        ("2026-09-30", "2026-09-30T23:00:00Z", 1), ("2026-10-07", "2026-10-07T23:00:00Z", 2)
    )
    assert list(HOURS.first_starts([week], {2})) == ["2026-10-07"]


def test_summary_names_each_trigger_hour_once() -> None:
    firsts = {
        "2026-11-04": datetime(2026, 11, 5, 0, 0, tzinfo=UTC),
        "2026-11-05": datetime(2026, 11, 6, 0, 30, tzinfo=UTC),
        "2026-11-06": datetime(2026, 11, 7, 0, 0, tzinfo=UTC),
    }
    summary = HOURS.summarize(firsts, 0)
    assert summary["minute"] == 0
    assert summary["hours"] == [0, 23]
    assert summary["days_per_hour"] == {"0": 1, "23": 2}
    assert HOURS.summarize(firsts, 37)["hours"] == [23]
    assert summary["first_puck_drops_et"] == {"19:00 EST": 2, "19:30 EST": 1}


_UTC_TIMES = st.datetimes(
    min_value=datetime(2000, 1, 1), max_value=datetime(2099, 1, 1), timezones=st.just(UTC)
)


@given(_UTC_TIMES, st.integers(min_value=0, max_value=59))
def test_the_derived_trigger_is_within_the_hour_before_the_puck_drop(
    first: datetime, minute: int
) -> None:
    hour = HOURS.last_hour_before(first, minute)
    candidates = [
        (first - timedelta(hours=back)).replace(minute=minute, second=0, microsecond=0)
        for back in (0, 1)
    ]
    trigger = max(c for c in candidates if c < first)
    assert trigger.hour == hour
    assert timedelta(0) < first - trigger <= timedelta(hours=1)


def test_derived_hours_match_the_runtime_rule() -> None:
    first = datetime(2026, 11, 5, 0, 30, tzinfo=UTC)
    hour = HOURS.last_hour_before(first, TRIGGER_MINUTE_UTC)
    assert hour == 23
    assert is_due(datetime(2026, 11, 4, hour, TRIGGER_MINUTE_UTC, tzinfo=UTC), first)


def test_minute_out_of_range_is_an_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        HOURS.main(["--from", "2026-11-04", "--to", "2026-11-05", "--minute", "60"])
    assert "--minute must be 0 to 59" in capsys.readouterr().err


def test_to_before_from_is_an_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        HOURS.main(["--from", "2026-11-05", "--to", "2026-11-04"])
    assert "is before --from" in capsys.readouterr().err
