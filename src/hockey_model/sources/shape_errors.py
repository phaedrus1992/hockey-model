"""The error raised when a source response parses but has an unknown shape."""

from hockey_model.sources.errors import SourceError


class SourceShapeError(SourceError):
    """Raised when a response parses but has an unknown shape."""
