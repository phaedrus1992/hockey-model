"""Tests that the daily-report workflow agrees with the trigger code."""

import re
from pathlib import Path

import pytest

from hockey_model.report_trigger import TRIGGER_INTERVAL_HOURS

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "daily-report.yml"
_CRON_HOURS = re.compile(r'cron: "0 \*/([0-9]+) \* \* \*"')


def test_cron_spacing_matches_the_trigger_interval() -> None:
    # The mutation run copies src and tests only, so it has no workflow file to read.
    if "mutants" in Path(__file__).resolve().parts:
        pytest.skip("the mutation copy has no .github directory")
    match = _CRON_HOURS.search(WORKFLOW.read_text(encoding="utf-8"))
    assert match is not None, "the schedule must be an hourly step cron such as '0 */N * * *'"
    assert int(match.group(1)) == TRIGGER_INTERVAL_HOURS
