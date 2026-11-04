"""The one UTC check that the public API and the report trigger share."""

from datetime import datetime, timedelta

from hockey_model.types import HockeyModelError


def require_utc(value: datetime, field: str) -> None:
    """Raise when ``value`` is naive or has an offset other than +00:00."""
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise HockeyModelError(
            f"{field} must be a timezone-aware UTC datetime (offset +00:00), got {value!r}"
        )
