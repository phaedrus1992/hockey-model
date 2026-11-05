"""The NHL game day: the Eastern calendar date that the NHL schedule and score feed use.

A game start is always a UTC instant. A day-level key, such as the report date or the
release tag, is the Eastern date of the slate, so one night's games stay in one report.
"""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from hockey_model.types import HockeyModelError

# The NHL dates its schedule in Eastern time. The score feed groups games by this date.
GAME_TIME_ZONE = ZoneInfo("America/New_York")


def game_day_window(day: date) -> tuple[datetime, datetime]:
    """Return the UTC instants that open and close the Eastern game day ``day``.

    The window is half-open. A day that changes daylight saving time is 23 or 25 hours long.
    """
    following = day + timedelta(days=1)
    opens = datetime(day.year, day.month, day.day, tzinfo=GAME_TIME_ZONE)
    closes = datetime(following.year, following.month, following.day, tzinfo=GAME_TIME_ZONE)
    return opens.astimezone(UTC), closes.astimezone(UTC)


def game_day_of(moment: datetime) -> date:
    """Return the Eastern game day that holds ``moment``. A naive time is an error."""
    if moment.tzinfo is None:
        raise HockeyModelError(
            f"game day of {moment!r}: the time has no timezone; pass a UTC datetime"
        )
    return moment.astimezone(GAME_TIME_ZONE).date()
