"""Property test: the membership of a goalie follows his newest game before the cutoff."""

import tempfile
from datetime import timedelta
from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from seeding import FETCHED, add_game, add_goalie, utc

from hockey_model.sources.teams import franchise
from hockey_model.store.db import connect
from hockey_model.store.membership import goalie_membership_before

BEFORE = utc("2026-02-01T00:00")
TEAMS = ["TOR", "MTL", "BOS"]
# A game counts once it started the result delay before the cutoff: 744 hours, less 3.
LAST_HOUR = 741
# (goalie id, team, hour of the start): each pair of goalie and hour is one game.
APPEARANCES = st.lists(
    st.tuples(st.integers(1, 3), st.sampled_from(TEAMS), st.integers(0, 40 * 24)),
    max_size=10,
    unique_by=lambda a: (a[0], a[2]),
)


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(APPEARANCES)
def test_departed_and_conflicting_goalies_follow_the_newest_game(
    appearances: list[tuple[int, str, int]],
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        conn = connect(Path(directory) / "store.db")
        try:
            base = utc("2026-01-01T00:00")
            for number, (nhl_id, team, hour) in enumerate(appearances, start=1):
                start = (base + timedelta(hours=hour)).strftime("%Y-%m-%dT%H:%M")
                add_game(conn, number, start, home=team, away="NYR")
                add_goalie(
                    conn,
                    number,
                    team,
                    nhl_id,
                    f"Goalie {nhl_id}",
                    fetched_at=FETCHED + timedelta(hours=number),
                )
            result = goalie_membership_before(conn, "TOR", {1, 2, 3}, BEFORE)
        finally:
            conn.close()
    assert result.departed.isdisjoint(result.conflicting)
    assert (result.departed | result.conflicting) <= {1, 2, 3}
    for nhl_id in (1, 2, 3):
        games = [a for a in appearances if a[0] == nhl_id and a[2] <= LAST_HOUR]
        if not games:
            assert nhl_id not in result.departed | result.conflicting
            continue
        newest = max(hour for _, _, hour in games)
        teams = {franchise(team) for _, team, hour in games if hour == newest}
        assert (nhl_id in result.departed) is (teams != {franchise("TOR")} and len(teams) == 1)
