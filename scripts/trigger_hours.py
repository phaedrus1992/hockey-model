"""Derive the report trigger hours from the NHL schedule of a season.

Usage:
    uv run python3 scripts/trigger_hours.py --from YYYY-MM-DD --to YYYY-MM-DD
        [--game-types 2,3] [--minute M]

For each Eastern game day, the script finds the first puck drop. It then finds the
last top-of-hour slot before that puck drop, moved earlier to the trigger minute of the hour
before it. Prints one JSON object:

    {"minute": 44, "hours": [0, 11, 15, 16, ...], "game_days": 183,
    "days_per_hour": {"23": 62, ...}, "first_puck_drops_et": {"19:00 EST": 52, ...}}

Compare "hours" with TRIGGER_HOURS_UTC in src/hockey_model/report_trigger.py, and copy a new
list into it and into the cron of .github/workflows/daily-report.yml. Re-run each season,
and again when the playoff schedule comes out.
"""

import argparse
import json
import sys
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime, timedelta
from typing import Any

from hockey_model.game_day import GAME_TIME_ZONE
from hockey_model.report_trigger import TRIGGER_MINUTE_UTC
from hockey_model.sources.http import HttpClient
from hockey_model.sources.nhl import NHL_BASE, SOURCE
from hockey_model.sources.payload import get_json


def trigger_hour_for(first: datetime, minute: int) -> int:
    """Return the UTC hour of the trigger that runs a game day with first puck drop ``first``.

    The trigger is the last top-of-hour slot strictly before ``first``, moved earlier to
    ``minute`` of the hour before it. Every listed trigger before the puck drop runs, so this
    hour is one of the runs that can publish.
    """
    slot = (first.astimezone(UTC) - timedelta(microseconds=1)).replace(
        minute=0, second=0, microsecond=0
    )
    return (slot - timedelta(minutes=60 - minute)).hour


def first_starts(weeks: Iterable[Mapping[str, Any]], game_types: set[int]) -> dict[str, datetime]:
    """Return the first start of each game day in the weekly schedule payloads."""
    firsts: dict[str, datetime] = {}
    for week in weeks:
        for game_day in week.get("gameWeek", []):
            for game in game_day.get("games", []):
                if game.get("gameType") not in game_types:
                    continue
                start = datetime.fromisoformat(game["startTimeUTC"].replace("Z", "+00:00"))
                key = game_day["date"]
                firsts[key] = min(firsts.get(key, start), start)
    return firsts


def summarize(firsts: Mapping[str, datetime], minute: int) -> dict[str, Any]:
    """Return the trigger hours that the first puck drops need, with their counts."""
    per_hour = Counter(trigger_hour_for(first, minute) for first in firsts.values())
    local = Counter(
        first.astimezone(GAME_TIME_ZONE).strftime("%H:%M %Z") for first in firsts.values()
    )
    return {
        "minute": minute,
        "hours": sorted(per_hour),
        "game_days": len(firsts),
        "days_per_hour": {str(hour): per_hour[hour] for hour in sorted(per_hour)},
        "first_puck_drops_et": dict(local.most_common()),
    }


def _weeks(client: HttpClient, first: date, last: date) -> list[Any]:
    # The schedule endpoint returns the week that starts on the given date.
    weeks = []
    day = first
    while day <= last:
        weeks.append(get_json(client, SOURCE, f"{NHL_BASE}/schedule/{day.isoformat()}"))
        day += timedelta(days=7)
    return weeks


def main(argv: list[str] | None = None) -> int:
    """Fetch the schedule and print the summary as JSON."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--from", dest="first", type=date.fromisoformat, required=True)
    parser.add_argument("--to", dest="last", type=date.fromisoformat, required=True)
    parser.add_argument("--game-types", default="2", help="comma-separated: 2 regular, 3 playoff")
    parser.add_argument(
        "--minute",
        type=int,
        default=TRIGGER_MINUTE_UTC,
        help="trigger minute of each hour; default is TRIGGER_MINUTE_UTC",
    )
    args = parser.parse_args(argv)
    if not 0 <= args.minute <= 59:
        parser.error(f"--minute must be 0 to 59, got {args.minute}")
    if args.last < args.first:
        parser.error(f"--to {args.last} is before --from {args.first}")
    game_types = {int(part) for part in args.game_types.split(",")}
    firsts = first_starts(_weeks(HttpClient(), args.first, args.last), game_types)
    json.dump(summarize(firsts, args.minute), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
