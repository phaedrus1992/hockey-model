#!/usr/bin/env bash
# Refresh the store, fit the model, and write the daily report for one UTC day.
#
# Usage: daily-report.sh --date YYYY-MM-DD --out-dir DIR [--help]
#   --date     UTC day to predict.
#   --out-dir  Directory for report-DATE.md and report-DATE.json. Created when missing.
#
# Reads the store path from HOCKEY_MODEL_DB. A missing store is backfilled from
# the first season the model uses. Any failed step stops the script with its exit code,
# so a run that fails writes no report.
set -euo pipefail

day=""
out_dir=""

usage() {
  sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'
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

if [[ -f "$HOCKEY_MODEL_DB" ]]; then
  uv run hockey-model refresh
else
  uv run hockey-model refresh --backfill-from 2014-10-01
fi
uv run hockey-model fit
uv run hockey-model daily --date "$day" --out-dir "$out_dir"
uv run hockey-model backtest --games-out "$out_dir/backtest-games-$day.csv" >"$out_dir/backtest-$day.json"
