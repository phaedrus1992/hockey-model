"""Decide whether one scheduled trigger publishes the daily report.

The scheduler fires at each trigger hour, in UTC. The report for a game day runs at the last
trigger before the first puck drop of that day. A game day with no games has its first puck
drop at the end of the day, so its report runs at the last trigger of the day.
Game days are Eastern dates: see game_day.py.
"""

from datetime import datetime, timedelta

from hockey_model.utc import require_utc

# The trigger spacing. The workflow cron MUST use the same spacing.
TRIGGER_INTERVAL_HOURS = 2


def next_trigger(now: datetime) -> datetime:
    """Return the first trigger time after the trigger that ``now`` falls in.

    A trigger that fires a little late still belongs to its own trigger slot.
    """
    require_utc(now, "report trigger now")
    slot = now.replace(minute=0, second=0, microsecond=0)
    slot -= timedelta(hours=slot.hour % TRIGGER_INTERVAL_HOURS)
    return slot + timedelta(hours=TRIGGER_INTERVAL_HOURS)


def first_puck_drop(day_closes: datetime, starts: list[datetime]) -> datetime:
    """Return the earliest start, or ``day_closes`` when the game day has no games."""
    require_utc(day_closes, "game day close")
    for start in starts:
        require_utc(start, "game start")
    return min(starts) if starts else day_closes


def is_due(now: datetime, first_start: datetime) -> bool:
    """Return True when no later trigger is still before the first puck drop.

    A puck drop that already passed makes every trigger due. The caller stops the
    repeat with the release check.
    """
    return next_trigger(now) >= first_start
