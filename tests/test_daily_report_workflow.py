"""Tests that the daily-report workflow agrees with the trigger code."""

import re
from pathlib import Path

import pytest

from hockey_model.report_trigger import TRIGGER_HOURS_UTC, TRIGGER_MINUTE_UTC

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "daily-report.yml"
_CRON = re.compile(r'cron: "([0-9]{1,2}) ([0-9,-]+) \* \* \*"')


def _hours(field: str) -> list[int]:
    """Expand a cron hour field such as ``0,1,16-23``."""
    hours: list[int] = []
    for part in field.split(","):
        low, _, high = part.partition("-")
        hours.extend(range(int(low), int(high or low) + 1))
    return hours


def test_cron_minute_and_hours_match_the_trigger_code() -> None:
    # The mutation run copies src and tests only, so it has no workflow file to read.
    if "mutants" in Path(__file__).resolve().parts:
        pytest.skip("the mutation copy has no .github directory")
    match = _CRON.search(WORKFLOW.read_text(encoding="utf-8"))
    assert match is not None, "the schedule must be an hourly cron such as '44 0,11,15-23 * * *'"
    assert int(match.group(1)) == TRIGGER_MINUTE_UTC
    assert _hours(match.group(2)) == list(TRIGGER_HOURS_UTC)


def test_prepare_runs_at_an_hour_with_no_trigger() -> None:
    prepare = WORKFLOW.with_name("daily-prepare.yml")
    if not prepare.exists():
        pytest.skip("the mutation copy has no .github directory")
    match = _CRON.search(prepare.read_text(encoding="utf-8"))
    assert match is not None
    (hour,) = _hours(match.group(2))
    assert hour not in TRIGGER_HOURS_UTC


def test_build_job_fails_loudly_on_a_store_cache_miss() -> None:
    # The mutation copy has no .github directory, so there is no workflow to read there.
    if "mutants" in Path(__file__).resolve().parts:
        pytest.skip("the mutation copy has no .github directory")
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "id: restore" in text
    # A restore hit on another branch is invisible; matched-key is empty when nothing restored.
    assert "steps.restore.outputs.cache-matched-key == ''" in text


def test_build_job_sets_the_report_budget_to_ten_minutes() -> None:
    # The mutation copy has no .github directory, so there is no workflow to read there.
    if "mutants" in Path(__file__).resolve().parts:
        pytest.skip("the mutation copy has no .github directory")
    assert 'REPORT_BUDGET_S: "600"' in WORKFLOW.read_text(encoding="utf-8")
