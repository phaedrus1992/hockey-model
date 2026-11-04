"""Decide whether one scheduled trigger publishes the daily report.

The scheduler fires at each hour in ``TRIGGER_HOURS_UTC``. The report for a game day runs at
the last trigger before the first puck drop of that day. A game day with no games has its
first puck drop at the end of the day, so its report runs at the last trigger of the day.
Game days are Eastern dates: see game_day.py. How the hours were chosen:
docs/design/daily-report-triggers.md.
"""

from datetime import datetime, timedelta

from hockey_model.utc import require_utc

# The UTC hours that hold a first puck drop's last trigger for the 2026-27 schedule, on an
# hourly grid. The workflow cron MUST list the same hours. Re-derive them each season.
TRIGGER_HOURS_UTC = (0, 1, 12, 16, 17, 18, 19, 20, 21, 22, 23)


def next_trigger(now: datetime) -> datetime:
    """Return the first trigger time strictly after ``now``.

    A trigger that fires a little late still sees the same next trigger, because no
    trigger hour lies between its own hour and ``now``.
    """
    require_utc(now, "report trigger now")
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    for hour in TRIGGER_HOURS_UTC:
        candidate = midnight + timedelta(hours=hour)
        if candidate > now:
            return candidate
    return midnight + timedelta(days=1, hours=TRIGGER_HOURS_UTC[0])


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
