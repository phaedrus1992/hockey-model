#!/usr/bin/env python3
# /// script
# requires-python = ">=3.14"
# ///
"""Fail when any source module is below the per-module coverage floor.

The aggregate pytest gate can pass while one module sits far below the rest.
This check reads coverage.json, written by pytest-cov, and checks each file
under src/ against the floor.

Usage: uv run python3 scripts/check_per_module_coverage.py [--floor PERCENT] [--report PATH]

Exit codes: 0 when every module meets the floor, 1 when any module is below it,
2 when the report is missing or malformed.

Output is one line per module on stdout. Diagnostics go to stderr.
"""

import argparse
import json
import sys
from pathlib import Path

DEFAULT_FLOOR = 80.0
DEFAULT_REPORT = Path("coverage.json")
SOURCE_PREFIX = "src/"


def load_percentages(report: Path) -> dict[str, float]:
    """Return the line coverage percent for each source file in the report.

    Raises ValueError when the report is not the coverage.py JSON shape.
    """
    try:
        data = json.loads(report.read_text(encoding="utf-8"))
        files = data["files"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError(f"cannot read coverage report {report}: {exc}") from exc
    return {
        name: float(entry["summary"]["percent_covered"])
        for name, entry in files.items()
        if name.startswith(SOURCE_PREFIX)
    }


def main(argv: list[str] | None = None) -> int:
    """Run the per-module check and return the process exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--floor", type=float, default=DEFAULT_FLOOR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    try:
        percentages = load_percentages(args.report)
    except ValueError as exc:
        print(f"error: {exc}. Run pytest first, so pytest-cov writes the report.", file=sys.stderr)
        return 2
    if not percentages:
        print(f"error: no files under {SOURCE_PREFIX} in {args.report}", file=sys.stderr)
        return 2
    failing = [name for name, pct in sorted(percentages.items()) if pct < args.floor]
    for name, pct in sorted(percentages.items()):
        print(f"{pct:6.2f}  {name}")
    if failing:
        print(f"error: below the {args.floor:.0f}% floor: {', '.join(failing)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
