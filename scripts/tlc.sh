#!/usr/bin/env bash
# Run TLC on the daily prepare spec. The jar is pinned by SHA-256 and checked on every run.
#
# Usage: bash scripts/tlc.sh [--workers N] [--help]
#   --workers N  TLC worker threads. Default: auto.
#   --help       Print this usage and exit 0.
#
# Environment:
#   TLA_TOOLS_DIR  Directory for the jar. Default: $HOME/.cache/hockey-model/tla.
#
# Exit codes: 0 when every property holds. 12 for a violated invariant. 13 for a violated
# action or temporal property. 1 for a setup failure, such as a bad checksum or no java.
# 2 for an unknown argument.
set -euo pipefail

TLA_TOOLS_VERSION="v1.7.4"
TLA_TOOLS_SHA256="936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88"
TLA_TOOLS_DIR="${TLA_TOOLS_DIR:-$HOME/.cache/hockey-model/tla}"
JAR="$TLA_TOOLS_DIR/tla2tools-$TLA_TOOLS_VERSION.jar"
WORKERS="auto"

usage() {
  sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
}

while (($# > 0)); do
  case "$1" in
    --workers)
      if (($# < 2)); then
        echo "tlc.sh: --workers needs a value, for example --workers 4" >&2
        exit 2
      fi
      WORKERS="$2"
      shift 2
      ;;
    --help)
      usage
      exit 0
      ;;
    *)
      echo "tlc.sh: unknown argument '$1'; run with --help for the usage" >&2
      exit 2
      ;;
  esac
done

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | cut -d ' ' -f 1
  else
    shasum -a 256 "$1" | cut -d ' ' -f 1
  fi
}

mkdir -p "$TLA_TOOLS_DIR"

if [[ ! -f "$JAR" ]]; then
  partial="$(mktemp "$TLA_TOOLS_DIR/download.XXXXXX")"
  trap 'rm -f "$partial"' EXIT
  curl -fsSL -o "$partial" \
    "https://github.com/tlaplus/tlaplus/releases/download/$TLA_TOOLS_VERSION/tla2tools.jar"
  mv "$partial" "$JAR"
  trap - EXIT
fi

actual="$(sha256_of "$JAR")"
if [[ "$actual" != "$TLA_TOOLS_SHA256" ]]; then
  rm -f "$JAR"
  echo "tlc.sh: checksum mismatch for $JAR" >&2
  echo "  expected: $TLA_TOOLS_SHA256" >&2
  echo "  actual:   $actual" >&2
  echo "  The file was deleted. Run the script again to download it." >&2
  exit 1
fi

if ! command -v java >/dev/null 2>&1; then
  echo "tlc.sh: java is not on PATH. Install Java 11 or later." >&2
  exit 1
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

set +e
java -XX:+UseParallelGC -cp "$JAR" tlc2.TLC -workers "$WORKERS" -cleanup -metadir "$tmp" \
  -config specs/daily_prepare.cfg specs/daily_prepare.tla
rc=$?
set -e

if ((rc != 0)); then
  echo "tlc.sh: TLC exited with code $rc. The counterexample trace is above." >&2
  exit "$rc"
fi
