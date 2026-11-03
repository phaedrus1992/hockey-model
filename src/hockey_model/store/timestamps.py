"""One text form for every time the store keeps: ISO 8601 in UTC."""

from datetime import UTC, datetime

from hockey_model.types import HockeyModelError


def iso_utc(moment: datetime) -> str:
    """Return ``moment`` as ISO 8601 UTC text. A naive time is an error."""
    if moment.tzinfo is None:
        raise HockeyModelError(f"store time {moment!r} has no timezone; pass a UTC datetime")
    return moment.astimezone(UTC).isoformat(timespec="microseconds")


def parse_iso_utc(text: str) -> datetime:
    """Parse text that ``iso_utc`` wrote."""
    return datetime.fromisoformat(text).astimezone(UTC)
