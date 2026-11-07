"""Tests that the constants in specs/daily_prepare.cfg match the values in the code."""

import re
from datetime import timedelta
from pathlib import Path

import pytest

from hockey_model.store.refresh_context import MAX_UNIT_FAILURES
from hockey_model.store.refresh_nhl import RETRY_FAILED_AFTER
from hockey_model.store.source_reads import ABANDON_AFTER_FAILED_READS, ABANDON_MIN_SPAN_DAYS

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "specs" / "daily_prepare.cfg"
# One shape per line: the name, an equals sign, and the value. Meaning is checked in code.
_CONSTANT_LINE = re.compile(r"^\s*([A-Za-z]+)\s*=\s*(.+?)\s*$")


def _constants() -> dict[str, str]:
    """Return the raw value of each ``NAME = value`` line in the CONSTANTS block."""
    values: dict[str, str] = {}
    in_block = False
    for line in CFG.read_text(encoding="utf-8").splitlines():
        if line.strip() == "CONSTANTS":
            in_block = True
            continue
        if in_block and line.strip() in {"INVARIANTS", "PROPERTIES", "SPECIFICATION"}:
            break
        match = _CONSTANT_LINE.match(line) if in_block else None
        if match:
            values[match.group(1)] = match.group(2)
    return values


def _integer(name: str) -> int:
    """Return the integer value of a constant, or fail and name the constant and the file."""
    raw = _constants().get(name)
    if raw is None:
        pytest.fail(f"{name} is missing from {CFG.relative_to(ROOT)}")
    if not re.fullmatch(r"[0-9]+", raw):
        pytest.fail(f"{name} in {CFG.relative_to(ROOT)} is {raw!r}, not an integer")
    return int(raw)


def test_abandon_reads_matches_code() -> None:
    assert _integer("AbandonReads") == ABANDON_AFTER_FAILED_READS


def test_abandon_ticks_is_one() -> None:
    # One tick is one failed read. The span rule in the code is checked by the model, not here.
    assert _integer("AbandonTicks") == 1


def test_retry_ticks_match_retry_window() -> None:
    span = timedelta(days=ABANDON_MIN_SPAN_DAYS) * _integer("RetryTicks")
    assert span == RETRY_FAILED_AFTER, (
        f"RetryTicks * ABANDON_MIN_SPAN_DAYS is {span}, but RETRY_FAILED_AFTER is "
        f"{RETRY_FAILED_AFTER}; update RetryTicks in {CFG.relative_to(ROOT)}"
    )


def test_max_fails_is_within_code_limit() -> None:
    max_fails = _integer("MaxFails")
    assert 1 <= max_fails <= MAX_UNIT_FAILURES, (
        f"MaxFails is {max_fails}; it must be between 1 and MAX_UNIT_FAILURES ({MAX_UNIT_FAILURES})"
    )


@pytest.mark.parametrize("name", ["AbandonReads", "AbandonTicks", "RetryTicks", "MaxFails"])
def test_missing_constant_fails_with_name(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    text = CFG.read_text(encoding="utf-8")
    stripped = re.sub(rf"(?m)^\s*{name}\s*=.*\n", "", text)
    monkeypatch.setattr(Path, "read_text", lambda self, **_: stripped)
    with pytest.raises(pytest.fail.Exception, match=name):
        _integer(name)
