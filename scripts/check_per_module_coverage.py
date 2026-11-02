#!/usr/bin/env python3
# /// script
# requires-python = ">=3.14"
# ///
"""Fail when a module under src/ is below the per-module coverage floor.

The aggregate pytest gate can pass while one module sits far below the rest.
This check reads coverage.json, written by pytest-cov, and checks every module
under src/ against the floor.

The floor comes from the --cov-fail-under flag in pyproject.toml, so the
aggregate gate and this gate share one number.

Usage: uv run python3 scripts/check_per_module_coverage.py

Exit codes: 0 when every module meets the floor, 1 when a module is below it,
2 when the report, the config, or the module list is missing or malformed.
Diagnostics go to stderr. The per-module lines go to stdout.
"""

import json
import math
import re
import sys
import tomllib
from pathlib import Path

PYPROJECT = Path("pyproject.toml")
REPORT = Path("coverage.json")
SOURCE_ROOT = Path("src")
SOURCE_PREFIX = "src/"
FLOOR_FLAG = re.compile(r"--cov-fail-under=([0-9]+(?:\.[0-9]+)?)")


def read_floor(pyproject: Path) -> float:
    """Return the floor from the --cov-fail-under flag in pytest addopts.

    Raises ValueError when the flag is absent or the value is outside 0 to 100.
    """
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        addopts = data["tool"]["pytest"]["ini_options"]["addopts"]
    except (OSError, tomllib.TOMLDecodeError, KeyError, TypeError) as exc:
        raise ValueError(f"cannot read pytest addopts from {pyproject}: {exc!r}") from exc
    if not isinstance(addopts, str):
        raise ValueError(f"addopts in {pyproject} must be a string, got {type(addopts).__name__}")
    match = FLOOR_FLAG.search(addopts)
    if match is None:
        raise ValueError(f"no --cov-fail-under flag in addopts of {pyproject}")
    floor = float(match.group(1))
    if not 0 <= floor <= 100:
        raise ValueError(f"--cov-fail-under in {pyproject} must be 0 to 100, got {floor:g}")
    return floor


def _reject_constant(report: Path, literal: str) -> None:
    """Refuse NaN and Infinity literals, which json.loads accepts by default."""
    raise ValueError(f"{report} contains the non-finite literal {literal}")


def load_report(report: Path) -> object:
    """Return the parsed coverage.json object.

    Raises ValueError when the file cannot be read or is not JSON. The read
    error names the step that writes the file.
    """
    try:
        text = report.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"cannot read {report} ({exc.strerror}); run pytest first") from exc
    try:
        return json.loads(text, parse_constant=lambda lit: _reject_constant(report, lit))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{report} is not valid JSON: {exc}") from exc


def _percent(name: str, entry: object) -> float:
    """Return summary.percent_covered for one file entry.

    Raises ValueError, naming the file key, when the value is missing or is not
    a finite number.
    """
    summary = entry.get("summary") if isinstance(entry, dict) else None
    value = summary.get("percent_covered") if isinstance(summary, dict) else None
    if value is None:
        raise ValueError(f"files[{name!r}] has no summary.percent_covered")
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ValueError(f"files[{name!r}].summary.percent_covered is not finite: {value!r}")
    return float(value)


def source_percentages(data: object) -> dict[str, float]:
    """Return the percent covered for each src/ file in a coverage.json object.

    Raises ValueError when the files object is missing or an entry is malformed.
    """
    files = data.get("files") if isinstance(data, dict) else None
    if not isinstance(files, dict):
        raise ValueError("coverage report has no 'files' object")
    return {
        name: _percent(name, entry)
        for name, entry in files.items()
        if name.startswith(SOURCE_PREFIX)
    }


def expected_modules() -> set[str]:
    """Return every module under src/, named the way coverage.py names it."""
    return {path.as_posix() for path in SOURCE_ROOT.rglob("*.py")}


def main() -> int:
    """Run the per-module check and return the process exit code."""
    try:
        floor = read_floor(PYPROJECT)
        percentages = source_percentages(load_report(REPORT))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not percentages:
        print(f"error: no modules under {SOURCE_ROOT}/ in {REPORT}", file=sys.stderr)
        return 2
    missing = sorted(expected_modules() - set(percentages))
    if missing:
        print(f"error: not in {REPORT}: {', '.join(missing)}", file=sys.stderr)
        return 2
    for name in sorted(percentages):
        print(f"{percentages[name]:>10.6g}  {name}")
    below = sorted(name for name, pct in percentages.items() if pct < floor)
    if below:
        print(f"error: below the {floor:g}% floor: {', '.join(below)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
