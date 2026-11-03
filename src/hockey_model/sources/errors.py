"""The error raised when an external source cannot be fetched."""

from hockey_model.types import HockeyModelError


class SourceError(HockeyModelError):
    """Raised when one external source cannot be fetched."""

    def __init__(self, source: str, url: str, reason: str) -> None:
        self.source = source
        self.url = url
        self.reason = reason
        super().__init__(f"fetch {source} {url}: {reason}; the stored data stays in use")
