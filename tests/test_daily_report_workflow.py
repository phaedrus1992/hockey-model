"""Tests that the daily-report workflow agrees with the trigger code."""

import re
from pathlib import Path

import pytest

from hockey_model.report_trigger import TRIGGER_HOURS_UTC

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "daily-report.yml"
_CRON = re.compile(r'cron: "0 ([0-9,-]+) \* \* \*"')


def _hours(field: str) -> list[int]:
    """Expand a cron hour field such as ``0,1,16-23``."""
    hours: list[int] = []
    for part in field.split(","):
        low, _, high = part.partition("-")
        hours.extend(range(int(low), int(high or low) + 1))
    return hours


def test_cron_hours_match_the_trigger_hours() -> None:
    # The mutation run copies src and tests only, so it has no workflow file to read.
    if "mutants" in Path(__file__).resolve().parts:
        pytest.skip("the mutation copy has no .github directory")
    match = _CRON.search(WORKFLOW.read_text(encoding="utf-8"))
    assert match is not None, "the schedule must be a top-of-hour cron such as '0 0,1,16-23 * * *'"
    assert _hours(match.group(1)) == list(TRIGGER_HOURS_UTC)


def test_prepare_runs_at_an_hour_with_no_trigger() -> None:
    prepare = WORKFLOW.with_name("daily-prepare.yml")
    if not prepare.exists():
        pytest.skip("the mutation copy has no .github directory")
    match = _CRON.search(prepare.read_text(encoding="utf-8"))
    assert match is not None
    (hour,) = _hours(match.group(1))
    assert hour not in TRIGGER_HOURS_UTC
