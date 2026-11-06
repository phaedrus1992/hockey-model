#!/usr/bin/env python3
# /// script
# requires-python = ">=3.14"
# ///
"""Decide the status of a mutation run and build its tracking-issue text.

A run has one of three statuses:

- ``clean``: the survivor count is at or below the baseline.
- ``regression``: the survivor count is above the baseline.
- ``execution_failed``: the stats are missing, malformed, or marked interrupted,
    or a shard did not finish.

The baseline is provisional. It is the survivor count from the first pass in #31.
Replace it when #31 publishes a machine-readable baseline.

Subcommands:

- ``status --stats FILE --execution success|failure``: print one status word.
- ``body --stats FILE --execution ... --run-url URL --out FILE``: write the issue body.
- ``find``: read ``gh issue list --json number,body`` JSON on stdin. Print the number
    of the open report, or print nothing when none exists.
- ``title``: print the title for a new report.

Diagnostics go to stderr. Exit 0 for a valid call. Exit 2 for a bad argument.

Usage: uv run python3 scripts/mutation_report.py status --stats mutants/mutmut-cicd-stats.json \
    --execution success
"""

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

MARKER = "<!-- hockey-model-mutation-report -->"
TITLE = "Mutation report: the weekly run needs a look"
PROVISIONAL_BASELINE = 524
COUNT_KEYS = ("killed", "survived", "timeout", "total")
STATUS_CLEAN = "clean"
STATUS_REGRESSION = "regression"
STATUS_FAILED = "execution_failed"


class MalformedStats(ValueError):
    """The stats file is missing, is not a JSON object, or has a bad count."""


@dataclass(frozen=True)
class Stats:
    """Survivor and outcome counts from ``mutmut export-cicd-stats``."""

    counts: dict[str, int]
    interrupted: bool


def read_stats(path: Path) -> Stats:
    """Read the stats file. Raise MalformedStats with the path and the bad field.

    A missing file, a file that is not JSON, and a count that is not a whole number
    all raise. A raise means the run did not finish, so the caller reports a failure.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise MalformedStats(f"cannot read {path}: {error.strerror}") from error
    except json.JSONDecodeError as error:
        raise MalformedStats(f"{path} is not JSON: {error.msg} at line {error.lineno}") from error
    if not isinstance(data, dict):
        raise MalformedStats(f"{path} must hold a JSON object, got {type(data).__name__}")
    counts: dict[str, int] = {}
    for key in COUNT_KEYS:
        value = data.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise MalformedStats(f"{path} field {key!r} must be a count, got {value!r}")
        counts[key] = value
    return Stats(counts=counts, interrupted=data.get("check_was_interrupted_by_user") is True)


def decide(stats: Stats | None, execution: str, baseline: int) -> str:
    """Return the status for one run.

    An interrupted run or a failed execution is never clean, even when its counts
    look fine, because the counts may be partial.
    """
    if execution != "success" or stats is None or stats.interrupted:
        return STATUS_FAILED
    if stats.counts["survived"] > baseline:
        return STATUS_REGRESSION
    return STATUS_CLEAN


def build_body(status: str, stats: Stats | None, baseline: int, run_url: str) -> str:
    """Return the Markdown body for the tracking issue.

    The body starts with the marker, so a later run finds this issue again.
    """
    lines = [MARKER, "", f"Status: `{status}`", f"Run: {run_url}", ""]
    if stats is None:
        lines.append("The run did not produce valid stats. Read the run log for the cause.")
    else:
        counts = stats.counts
        difference = counts["survived"] - baseline
        lines += [
            "| Killed | Survived | Timed out | Total | Baseline | Difference |",
            "| --- | --- | --- | --- | --- | --- |",
            f"| {counts['killed']} | {counts['survived']} | {counts['timeout']} | "
            f"{counts['total']} | {baseline} | {difference:+d} |",
        ]
    return "\n".join(lines) + "\n"


def find_open_report(issues_json: str) -> int | None:
    """Return the number of the first open issue that carries the marker.

    Raise ValueError when the input is not a JSON list of objects with a number.
    """
    issues = json.loads(issues_json)
    if not isinstance(issues, list):
        raise ValueError("issue list must be a JSON array")
    for issue in issues:
        if not isinstance(issue, dict) or not isinstance(issue.get("number"), int):
            raise ValueError(f"issue entry needs an integer number, got {issue!r}")
        if MARKER in (issue.get("body") or ""):
            return issue["number"]
    return None


def _load_stats_or_none(path: Path) -> Stats | None:
    """Read the stats, or print the reason to stderr and return None."""
    try:
        return read_stats(path)
    except MalformedStats as error:
        print(f"mutation-report: {error}", file=sys.stderr)
        return None


def _parser() -> argparse.ArgumentParser:
    """Build the argument parser for the three subcommands."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "body"):
        command = sub.add_parser(name)
        command.add_argument("--stats", type=Path, required=True)
        command.add_argument("--execution", choices=("success", "failure"), required=True)
        command.add_argument("--baseline", type=int, default=PROVISIONAL_BASELINE)
        if name == "body":
            command.add_argument("--run-url", required=True)
            command.add_argument("--out", type=Path, required=True)
    sub.add_parser("find")
    sub.add_parser("title")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run one subcommand and return its exit code."""
    args = _parser().parse_args(argv)
    if args.command == "title":
        print(TITLE)
        return 0
    if args.command == "find":
        number = find_open_report(sys.stdin.read())
        if number is not None:
            print(number)
        return 0
    stats = _load_stats_or_none(args.stats)
    status = decide(stats, args.execution, args.baseline)
    if args.command == "status":
        print(status)
        return 0
    args.out.write_text(build_body(status, stats, args.baseline, args.run_url), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
