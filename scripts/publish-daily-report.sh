#!/usr/bin/env bash
# Publish the daily report as a GitHub release tagged reports-DATE.
#
# Usage: publish-daily-report.sh --date YYYY-MM-DD --report-dir DIR [--help]
#   --date        UTC day of the report.
#   --report-dir  Directory that holds report-DATE.md and report-DATE.json.
#
# A release that already exists for the day is an error. Delete the release to publish
# the day again. The script never replaces a release on its own.
set -euo pipefail

day=""
report_dir=""

usage() {
  sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'
}

while (($# > 0)); do
  case "$1" in
    --date)
      day="${2:?publish-daily-report: --date needs a value YYYY-MM-DD; see --help}"
      shift 2
      ;;
    --report-dir)
      report_dir="${2:?publish-daily-report: --report-dir needs a directory; see --help}"
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

md="$report_dir/report-$day.md"
json="$report_dir/report-$day.json"
for file in "$md" "$json"; do
  if [[ ! -s "$file" ]]; then
    echo "publish-daily-report: $file is missing or empty; the report was not built" >&2
    exit 1
  fi
done

tag="reports-$day"
# The full list, so an existing release is found whatever its age in the list.
released="$(gh release list --limit 1000 --json tagName --jq '.[].tagName')"
if grep -qxF "$tag" <<<"$released"; then
  echo "publish-daily-report: release $tag already exists; delete it to publish $day again" >&2
  exit 1
fi

gh release create "$tag" "$md" "$json" \
  --title "NHL predictions $day" \
  --notes-file "$md"
