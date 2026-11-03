"""NHL team code maps. Each source writes its own codes, so each map converts to the NHL code.

Daily Faceoff and MoneyPuck maps are added with their sources (plan Tasks 6 and 8).
"""

from hockey_model.sources.shape_errors import SourceShapeError

# The 32 current teams, plus ARI for seasons before the 2024-25 move to UTA.
NHL_TEAM_CODES: frozenset[str] = frozenset(
    "ANA BOS BUF CAR CBJ CGY CHI COL DAL DET EDM FLA LAK MIN MTL NJD NSH NYI NYR OTT PHI "
    "PIT SEA SJS STL TBL TOR UTA VAN VGK WPG WSH ARI".split()
)

# ESPN writes four codes that differ from the NHL codes. Other codes match as written.
_ESPN_TO_NHL = {"LA": "LAK", "NJ": "NJD", "SJ": "SJS", "TB": "TBL"}

# Arizona played as ARI until 2024-25, then as UTA. Ratings and rest follow the franchise.
_FRANCHISE = {"ARI": "UTA"}


def franchise(code: str) -> str:
    """Return the franchise code for an NHL team code, so one team keeps one history."""
    return _FRANCHISE.get(code, code)


def from_espn(code: str) -> str:
    """Return the NHL code for a code that ESPN writes."""
    nhl = _ESPN_TO_NHL.get(code, code)
    if nhl not in NHL_TEAM_CODES:
        raise SourceShapeError(
            "espn",
            "team code",
            f"unknown ESPN team code {code!r}; add it to sources/teams.py",
        )
    return nhl
