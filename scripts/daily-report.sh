#!/usr/bin/env bash
# Write the daily report for one game day: refresh the starters, then predict.
#
# Usage: daily-report.sh --date YYYY-MM-DD --out-dir DIR [--help]
#   --date     Eastern game day to predict.
#   --out-dir  Directory for the report and backtest files. Created when missing.
#
# Reads the store path from HOCKEY_MODEL_DB. The morning run of daily-prepare.sh does the
# slow work. When its prepared-DATE marker is missing, this script runs it first, so a
# late or failed morning run still gives a report. Any failed step stops the script with
# its exit code, so a failed run writes no report.
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

store_dir="$(dirname "$HOCKEY_MODEL_DB")"
mkdir -p "$out_dir"
if [[ ! -f "$store_dir/prepared-$day" ]]; then
  echo "daily-report: no morning preparation for $day; preparing now." >&2
  bash "$(dirname "$0")/daily-prepare.sh" --date "$day"
else
  uv run hockey-model refresh --starters-only
fi
uv run hockey-model daily --date "$day" --out-dir "$out_dir"
cp "$store_dir/backtest-$day.json" "$store_dir/backtest-games-$day.csv" "$out_dir/"
