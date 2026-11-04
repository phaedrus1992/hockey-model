"""Tests that the daily-report workflow agrees with the trigger code."""

import re
from pathlib import Path

from hockey_model.report_trigger import TRIGGER_INTERVAL_HOURS

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "daily-report.yml"
_CRON_HOURS = re.compile(r'cron: "0 \*/([0-9]+) \* \* \*"')


def test_cron_spacing_matches_the_trigger_interval() -> None:
    match = _CRON_HOURS.search(WORKFLOW.read_text(encoding="utf-8"))
    assert match is not None, "the schedule must be an hourly step cron such as '0 */N * * *'"
    assert int(match.group(1)) == TRIGGER_INTERVAL_HOURS
