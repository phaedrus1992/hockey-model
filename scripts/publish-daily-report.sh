#!/usr/bin/env bash
# Publish the daily report as a GitHub release tagged reports-DATE.
#
# Usage: publish-daily-report.sh --date YYYY-MM-DD --report-dir DIR [--help]
#   --date        Eastern game day of the report.
#   --report-dir  Directory with report-DATE.md, report-DATE.json, backtest-DATE.json,
#                 and backtest-games-DATE.csv.
#
# The release target is GITHUB_SHA, the commit that built the report. A release that
# already exists for the day makes gh fail, and the script never replaces it. Delete the
# release to publish the day again.
set -euo pipefail

day=""
report_dir=""

usage() {
  sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'
}

while (($# > 0)); do
  case "$1" in
    --date)
      if (($# < 2)); then
        echo "publish-daily-report: --date needs a value YYYY-MM-DD; see --help" >&2
        exit 2
      fi
      day="$2"
      shift 2
      ;;
    --report-dir)
      if (($# < 2)); then
        echo "publish-daily-report: --report-dir needs a directory; see --help" >&2
        exit 2
      fi
      report_dir="$2"
      shift 2
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      echo "publish-daily-report: unknown argument '$1'; see --help" >&2
      exit 2
      ;;
  esac
done

if [[ -z "$day" || -z "$report_dir" ]]; then
  echo "publish-daily-report: --date and --report-dir are required; see --help" >&2
  exit 2
fi
# The date goes into a tag and a path, so it must have exactly the calendar shape.
if [[ ! "$day" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
  echo "publish-daily-report: --date must be YYYY-MM-DD, got '$day'" >&2
  exit 2
fi
if [[ -z "${GITHUB_SHA:-}" ]]; then
  echo "publish-daily-report: GITHUB_SHA must name the commit that built the report" >&2
  exit 2
fi

md="$report_dir/report-$day.md"
json="$report_dir/report-$day.json"
backtest="$report_dir/backtest-$day.json"
backtest_games="$report_dir/backtest-games-$day.csv"
for file in "$md" "$json" "$backtest" "$backtest_games"; do
  if [[ ! -s "$file" ]]; then
    echo "publish-daily-report: $file is missing or empty; the report was not built" >&2
    exit 1
  fi
done
for file in "$json" "$backtest"; do
  if ! jq -e . "$file" >/dev/null; then
    echo "publish-daily-report: $file is not valid JSON; the report was not published" >&2
    exit 1
  fi
done
if [[ "$(head -n 1 "$backtest_games")" != *,* ]]; then
  echo "publish-daily-report: $backtest_games has no CSV header; the backtest was not built" >&2
  exit 1
fi

tag="reports-$day"
gh release create "$tag" "$md" "$json" "$backtest" "$backtest_games" \
  --target "$GITHUB_SHA" \
  --title "NHL predictions $day" \
  --notes-file "$md"
