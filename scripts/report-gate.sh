#!/usr/bin/env bash
# Decide whether this scheduled trigger publishes the daily report.
#
# Usage: report-gate.sh [--date YYYY-MM-DD] [--force] [--dry-run] [--help]
#   --date   Eastern game day to check. Default: the game day that holds now.
#   --force  Publish even outside the trigger slot. A day that is already
#            published is still skipped.
#   --dry-run  Build a report that the caller does not publish. This implies --force,
#            and the published-release check is skipped, so a published day is due again.
#
# Prints one JSON object on stdout:
#   {"due": bool, "publish": bool, "tag": str, "reason": str, "date": str}.
# "due" says the report is built. "publish" says the report becomes a release, and it is
# false for --dry-run.
# Exits non-zero when the schedule payload is malformed or the release lookup fails.
set -euo pipefail

day=""
force=false
dry_run=false

usage() {
  sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'
}

while (($# > 0)); do
  case "$1" in
    --date)
      if (($# < 2)); then
        echo "report-gate: --date needs a value YYYY-MM-DD; see --help" >&2
        exit 2
      fi
      day="$2"
      shift 2
      ;;
    --force)
      force=true
      shift
      ;;
    --dry-run)
      dry_run=true
      force=true
      shift
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      echo "report-gate: unknown argument '$1'; see --help" >&2
      exit 2
      ;;
  esac
done

# The schedule read is one HTTP request. The release lookup runs only when a
# trigger is due, so a day that is not due costs one request.
# Without --date, report-due picks the Eastern game day that holds now.
args=()
if [[ -n "$day" ]]; then
  args+=(--date "$day")
fi
if [[ "$force" == true ]]; then
  args+=(--force)
fi
status_json="$(uv run hockey-model report-due ${args[@]+"${args[@]}"})"
required='(.due | type == "boolean") and (.tag | type == "string")'
required+=' and (.games | type == "number") and (.date | type == "string")'
if ! jq -e "$required" <<<"$status_json" >/dev/null; then
  echo "report-gate: report-due payload lacks due, tag, games, or date: $status_json" >&2
  exit 1
fi
tag="$(jq -r '.tag' <<<"$status_json")"
due="$(jq -r '.due' <<<"$status_json")"
games="$(jq -r '.games' <<<"$status_json")"
day="$(jq -r '.date' <<<"$status_json")"
if [[ "$games" == "0" ]]; then
  echo "::warning::report-gate: the schedule lists no games for $day; the report will say so" >&2
fi

reason="not-due"
if [[ "$due" == "true" && "$dry_run" == true ]]; then
  reason="dry-run"
elif [[ "$due" == "true" ]]; then
  reason="due"
  # Ask for the one tag. "release not found" means the day is not published yet; any
  # other failure (auth, network) stops the run.
  view_err="$(gh release view "$tag" 2>&1 >/dev/null)" && published=true || published=false
  if [[ "$published" == true ]]; then
    due="false"
    reason="already-published"
  elif [[ "$view_err" != *"release not found"* ]]; then
    echo "report-gate: gh release view $tag failed: $view_err" >&2
    exit 1
  fi
fi

publish="$due"
if [[ "$dry_run" == true ]]; then
  publish="false"
fi
jq -n --argjson due "$due" --argjson publish "$publish" --arg tag "$tag" --arg reason "$reason" \
  --arg date "$day" '{due: $due, publish: $publish, tag: $tag, reason: $reason, date: $date}'
