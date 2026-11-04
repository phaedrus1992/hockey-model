"""Decide whether one scheduled trigger publishes the daily report.

The scheduler fires at each trigger hour, in UTC. The report runs at the last trigger before
the first puck drop of the UTC day. A day with no games has its first puck drop at the next
UTC midnight, so its report runs at the last trigger of the day.
"""

from datetime import UTC, date, datetime, timedelta

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


def day_end(day: date) -> datetime:
    """Return the UTC midnight that ends ``day``."""
    return datetime(day.year, day.month, day.day, tzinfo=UTC) + timedelta(days=1)


def first_puck_drop(day: date, starts: list[datetime]) -> datetime:
    """Return the earliest start of the day, or the end of the day when no game starts."""
    for start in starts:
        require_utc(start, "game start")
    return min(starts) if starts else day_end(day)


def is_due(now: datetime, first_start: datetime) -> bool:
    """Return True when no later trigger is still before the first puck drop.

    A puck drop that already passed makes every trigger due. The caller stops the
    repeat with the release check.
    """
    return next_trigger(now) >= first_start
