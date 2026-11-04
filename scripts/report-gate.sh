#!/usr/bin/env bash
# Decide whether this scheduled trigger publishes the daily report.
#
# Usage: report-gate.sh [--date YYYY-MM-DD] [--force] [--help]
#   --date   UTC day to check. Default: today in UTC.
#   --force  Publish even outside the trigger slot. A day that is already
#            published is still skipped.
#
# Prints one JSON object on stdout: {"due": bool, "tag": str, "reason": str}.
# Exits non-zero when the schedule payload is malformed or the release lookup fails.
set -euo pipefail

day=""
force=false

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

day="${day:-$(date -u +%F)}"

# The schedule read is one HTTP request. The release lookup runs only when a
# trigger is due, so a day that is not due costs one request.
args=(--date "$day")
if [[ "$force" == true ]]; then
  args+=(--force)
fi
status_json="$(uv run hockey-model report-due "${args[@]}")"
if ! jq -e '(.due | type == "boolean") and (.tag | type == "string") and (.games | type == "number")' \
  <<<"$status_json" >/dev/null; then
  echo "report-gate: report-due printed a payload without due, tag, and games: $status_json" >&2
  exit 1
fi
tag="$(jq -r '.tag' <<<"$status_json")"
due="$(jq -r '.due' <<<"$status_json")"
games="$(jq -r '.games' <<<"$status_json")"
if [[ "$games" == "0" ]]; then
  echo "::warning::report-gate: the schedule lists no games for $day; the report will say so" >&2
fi

reason="not-due"
if [[ "$due" == "true" ]]; then
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

jq -n --argjson due "$due" --arg tag "$tag" --arg reason "$reason" \
  '{due: $due, tag: $tag, reason: $reason}'
