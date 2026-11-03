"""The NHL team code set, shared by the public game type and the source maps."""

# The 32 current teams, plus ARI for seasons before the 2024-25 move to UTA.
NHL_TEAM_CODES: frozenset[str] = frozenset(
    "ANA BOS BUF CAR CBJ CGY CHI COL DAL DET EDM FLA LAK MIN MTL NJD NSH NYI NYR OTT PHI "
    "PIT SEA SJS STL TBL TOR UTA VAN VGK WPG WSH ARI".split()
)
