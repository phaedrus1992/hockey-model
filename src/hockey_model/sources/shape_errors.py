"""The error raised when a source value has no known NHL team code."""

from hockey_model.types import HockeyModelError


class SourceShapeError(HockeyModelError):
    """Raised when a source writes a team code that the maps do not know."""

    def __init__(self, source: str, value: str) -> None:
        self.source = source
        self.value = value
        super().__init__(
            f"map {source} team code {value!r}: unknown code; add it to sources/teams.py"
        )
