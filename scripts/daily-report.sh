#!/usr/bin/env bash
# Refresh the store, fit the model, and write the daily report and backtest for one UTC day.
#
# Usage: daily-report.sh --date YYYY-MM-DD --out-dir DIR [--help]
#   --date     UTC day to predict.
#   --out-dir  Directory for the report and backtest files. Created when missing.
#
# Reads the store path from HOCKEY_MODEL_DB. The first backfill runs until a marker file
# next to the store says it finished. An interrupted backfill resumes on the next run,
# because refresh skips what it already read. Any failed step stops the script with its
# exit code, so a failed run writes no report.
set -euo pipefail

day=""
out_dir=""

usage() {
  sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'
}

while (($# > 0)); do
  case "$1" in
    --date)
      day="${2:?daily-report: --date needs a value YYYY-MM-DD; see --help}"
      shift 2
      ;;
    --out-dir)
      out_dir="${2:?daily-report: --out-dir needs a directory; see --help}"
      shift 2
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      echo "daily-report: unknown argument '$1'; see --help" >&2
      exit 2
      ;;
  esac
done

if [[ -z "$day" || -z "$out_dir" ]]; then
  echo "daily-report: --date and --out-dir are required; see --help" >&2
  exit 2
fi
if [[ -z "${HOCKEY_MODEL_DB:-}" ]]; then
  echo "daily-report: HOCKEY_MODEL_DB must name the store file; see --help" >&2
  exit 2
fi

mkdir -p "$(dirname "$HOCKEY_MODEL_DB")" "$out_dir"

# The marker is written only after a backfill finishes. A store file without it is partial.
marker="$HOCKEY_MODEL_DB.backfilled"
if [[ ! -f "$marker" ]]; then
  echo "daily-report: the store has no finished backfill; backfilling from 2014-10-01." >&2
  echo "daily-report: a full backfill takes hours and can outlast the job time limit." >&2
  uv run hockey-model refresh --backfill-from 2014-10-01
  touch "$marker"
else
  uv run hockey-model refresh
fi
uv run hockey-model fit
uv run hockey-model daily --date "$day" --out-dir "$out_dir"
uv run hockey-model backtest --games-out "$out_dir/backtest-games-$day.csv" >"$out_dir/backtest-$day.json"
