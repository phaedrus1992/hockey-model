#!/usr/bin/env bash
# Write the daily report for one game day: refresh the starters, then predict.
#
# Usage: daily-report.sh --date YYYY-MM-DD --out-dir DIR [--help]
#   --date     Eastern game day to predict.
#   --out-dir  Directory for the report and backtest files. Created when missing.
#
# Reads the store path from HOCKEY_MODEL_DB. The morning run of daily-prepare.sh does the
# slow work. When its prepared-DATE marker is missing, this script stops with exit code 1
# and writes no report, because the slow work does not fit before the puck drop. Run the
# daily-prepare workflow for the day, then run this script again. Any failed step stops
# the script with its exit code, so a failed run writes no report.
set -euo pipefail

day=""
out_dir=""

usage() {
  sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'
}

while (($# > 0)); do
  case "$1" in
    --date)
      if (($# < 2)); then
        echo "daily-report: --date needs a value YYYY-MM-DD; see --help" >&2
        exit 2
      fi
      day="$2"
      shift 2
      ;;
    --out-dir)
      if (($# < 2)); then
        echo "daily-report: --out-dir needs a directory; see --help" >&2
        exit 2
      fi
      out_dir="$2"
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
# The day names files next to the store, so only a real date may pass.
# shellcheck source=scripts/valid-day.sh
source "$(dirname "$0")/valid-day.sh"
if ! is_valid_day "$day"; then
  echo "daily-report: --date '$day' is not a real date YYYY-MM-DD; see --help" >&2
  exit 2
fi
if [[ -z "${HOCKEY_MODEL_DB:-}" ]]; then
  echo "daily-report: HOCKEY_MODEL_DB must name the store file; see --help" >&2
  exit 2
fi

store_dir="$(dirname "$HOCKEY_MODEL_DB")"
mkdir -p "$out_dir"
if [[ ! -f "$store_dir/prepared-$day" ]]; then
  echo "daily-report: no preparation for $day in $store_dir." >&2
  echo "daily-report: run the daily-prepare workflow with date $day, then run this again." >&2
  echo "daily-report: if it ran, check that it passed and that the store came back from the cache." >&2
  exit 1
fi
uv run hockey-model refresh --starters-only
uv run hockey-model daily --date "$day" --out-dir "$out_dir"
cp "$store_dir/backtest-$day.json" "$store_dir/backtest-games-$day.csv" "$out_dir/"
