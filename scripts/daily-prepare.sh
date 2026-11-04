#!/usr/bin/env bash
# Prepare one game day: refresh every source, fit the model, and run the backtest.
#
# Usage: daily-prepare.sh [--date YYYY-MM-DD] [--help]
#   --date  Eastern game day to prepare. Default: today in Eastern time.
#
# Reads the store path from HOCKEY_MODEL_DB. The first backfill runs until a marker file
# next to the store says it finished. An interrupted backfill resumes on the next run,
# because refresh skips what it already read. The backtest files and a prepared-DATE
# marker go next to the store, where daily-report.sh finds them. Any failed step stops
# the script with its exit code, so a failed run writes no marker.
set -euo pipefail

day=""

usage() {
  sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'
}

while (($# > 0)); do
  case "$1" in
    --date)
      day="${2:?daily-prepare: --date needs a value YYYY-MM-DD; see --help}"
      shift 2
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      echo "daily-prepare: unknown argument '$1'; see --help" >&2
      exit 2
      ;;
  esac
done

if [[ -z "${HOCKEY_MODEL_DB:-}" ]]; then
  echo "daily-prepare: HOCKEY_MODEL_DB must name the store file; see --help" >&2
  exit 2
fi
# The game day is the Eastern date, as GAME_TIME_ZONE in src/hockey_model/game_day.py says.
day="${day:-$(TZ=America/New_York date +%F)}"
store_dir="$(dirname "$HOCKEY_MODEL_DB")"
mkdir -p "$store_dir"

# The marker is written only after a backfill finishes. A store file without it is partial.
marker="$HOCKEY_MODEL_DB.backfilled"
if [[ ! -f "$marker" ]]; then
  echo "daily-prepare: the store has no finished backfill; backfilling from 2014-10-01." >&2
  echo "daily-prepare: a full backfill takes hours and can outlast the job time limit." >&2
  uv run hockey-model refresh --backfill-from 2014-10-01
  touch "$marker"
else
  uv run hockey-model refresh
fi
uv run hockey-model fit

# Files from earlier days are stale. The release of each day already holds its own copy.
find "$store_dir" -maxdepth 1 -type f \( -name 'prepared-*' -o -name 'backtest-*' \) -delete
backtest_games="$store_dir/backtest-games-$day.csv"
uv run hockey-model backtest --games-out "$backtest_games" >"$store_dir/backtest-$day.json"
touch "$store_dir/prepared-$day"
