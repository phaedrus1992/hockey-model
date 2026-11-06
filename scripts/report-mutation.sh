#!/usr/bin/env bash
# Files, updates, or comments on the one open mutation report for a run.
#
# Usage: scripts/report-mutation.sh --stats FILE --execution success|failure --run-url URL
#
# A regression or an execution failure opens the report, or comments on the open one.
# A clean run comments a recovery note on an open report and leaves it open, so the
# owner closes it. Run only from a job that holds issues: write on the default branch.
#
# Stdout: the status word (clean, regression, or execution_failed).
# Stderr: diagnostics. Exit 0 when the report is filed. Exit 2 on bad arguments.
set -euo pipefail

STATS=""
EXECUTION=""
RUN_URL=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --stats)
      STATS="${2:-}"
      shift 2
      ;;
    --execution)
      EXECUTION="${2:-}"
      shift 2
      ;;
    --run-url)
      RUN_URL="${2:-}"
      shift 2
      ;;
    --help | -h)
      sed -n '2,11p' "$0"
      exit 0
      ;;
    *)
      echo "report-mutation: unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [[ -z "$STATS" || -z "$EXECUTION" || -z "$RUN_URL" ]]; then
  echo "report-mutation: --stats, --execution, and --run-url are all required" >&2
  exit 2
fi

readonly HELPER="scripts/mutation_report.py"
readonly BODY=".tmp/mutation-report.md"
mkdir -p .tmp

status="$(uv run python3 "$HELPER" status --stats "$STATS" --execution "$EXECUTION")"
uv run python3 "$HELPER" body --stats "$STATS" --execution "$EXECUTION" \
  --run-url "$RUN_URL" --out "$BODY"
title="$(uv run python3 "$HELPER" title)"

issues="$(gh issue list --state open --limit 200 --json number,body)"
existing="$(printf '%s' "$issues" | uv run python3 "$HELPER" find)"

if [[ "$status" == "clean" ]]; then
  if [[ -n "$existing" ]]; then
    gh issue comment "$existing" --body "Recovery: the weekly run $RUN_URL is clean. Survivors are at or below the baseline. Close this report when you accept the result." >&2
  fi
elif [[ -n "$existing" ]]; then
  gh issue comment "$existing" --body-file "$BODY" >&2
else
  gh issue create --title "$title" --body-file "$BODY" >&2
fi

echo "$status"
