"""Tests for scripts/tlc.sh argument handling. These paths exit before any download."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "tlc.sh"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), *args], capture_output=True, text=True, check=False, timeout=30
    )


def test_help_prints_usage_and_exits_zero() -> None:
    result = _run("--help")
    assert result.returncode == 0
    assert "Usage: bash scripts/tlc.sh" in result.stdout


def test_unknown_argument_exits_two_and_names_it() -> None:
    result = _run("--bogus")
    assert result.returncode == 2
    assert "'--bogus'" in result.stderr


def test_workers_without_value_exits_two() -> None:
    result = _run("--workers")
    assert result.returncode == 2
    assert "--workers needs a value" in result.stderr
