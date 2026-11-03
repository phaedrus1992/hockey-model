"""Decide which goalie starts a game, and say how sure the answer is."""

import sqlite3
from collections import Counter
from datetime import datetime
from functools import cached_property

from hockey_model.game import (
    Game,
    GoalieStart,
    MissingInput,
    MissingKind,
    StarterSource,
    StarterStatus,
)
from hockey_model.game_model.names import matching_players
from hockey_model.identity import Catalog
from hockey_model.store.reads import (
    StarterReadRow,
    franchise_codes,
    goalie_starts_before,
    injury_reads_before,
    player_catalog,
    starter_reads_before,
)
from hockey_model.store.timestamps import parse_iso_utc
from hockey_model.types import Player, Slot

# The guess counts starts in this many of the newest games of the team.
STARTER_WINDOW = 10


class _Goalies:
    """The goalies of the store, found by name. The lists are built on first use."""

    def __init__(self, catalog: Catalog, team: str) -> None:
        self.catalog = catalog
        self._team_code = team

    @cached_property
    def league(self) -> list[Player]:
        return [p for p in self.catalog.players if p.eligible == frozenset({Slot.G})]

    @cached_property
    def team(self) -> list[Player]:
        codes = franchise_codes(self._team_code)
        return [p for p in self.league if p.team_code in codes]

    def find(self, name: str) -> tuple[Player | None, str]:
        """Return the goalie that ``name`` means, or ``None`` and the reason.

        A goalie that was traded may not have played for the new team yet, so a name
        that matches nobody on the team is looked up in the whole league. Two matches
        are never resolved by a guess.
        """
        for pool in (self.team, self.league):
            found = matching_players(name, pool)
            if len(found) == 1:
                return found[0], ""
            if len(found) > 1:
                return None, f"goalie name {name!r} matches {len(found)} goalies"
        return None, f"goalie name {name!r} matches no goalie in the store"


def _unknown(team: str, note: str) -> MissingInput:
    return MissingInput(MissingKind.GOALIE_UNKNOWN, team, note)


def boxscore_starter(
    conn: sqlite3.Connection, game: Game, team: str, catalog: Catalog
) -> GoalieStart | None:
    row = conn.execute(
        "SELECT nhl_id, fetched_at FROM goalie_games WHERE game_id = ? AND team = ?"
        " AND started = 1",
        (game.game_id, team),
    ).fetchone()
    if row is None:
        return None
    return GoalieStart(
        catalog.resolve(row[0]),
        StarterStatus.CONFIRMED,
        StarterSource.NHL_BOXSCORE,
        parse_iso_utc(row[1]),
    )


def _start_from(read: StarterReadRow, player: Player) -> GoalieStart:
    source = StarterSource(read.source)
    return GoalieStart(player, read.status, source, read.fetched_at)


def _from_reads(
    reads: list[StarterReadRow], goalies: _Goalies, team: str
) -> tuple[GoalieStart | None, list[MissingInput]]:
    """Pick the earliest confirmed read, else the newest likely read."""
    notes: list[MissingInput] = []
    confirmed: GoalieStart | None = None
    likely: GoalieStart | None = None
    for read in reads:
        if read.status is StarterStatus.UNKNOWN:
            continue
        player, why = goalies.find(read.goalie_name)
        if player is None:
            notes.append(_unknown(team, why))
        elif read.status is StarterStatus.CONFIRMED and confirmed is None:
            confirmed = _start_from(read, player)
        elif read.status is StarterStatus.LIKELY:
            likely = _start_from(read, player)
    if confirmed is not None:
        return confirmed, notes
    if likely is not None:
        note = f"{likely.player.full_name} is likely, not confirmed"
        notes.append(MissingInput(MissingKind.GOALIE_UNCONFIRMED, team, note))
    return likely, notes


def _guess(
    conn: sqlite3.Connection, goalies: _Goalies, team: str, as_of: datetime
) -> GoalieStart | None:
    starts = goalie_starts_before(conn, team, as_of, STARTER_WINDOW)
    counts = Counter(nhl_id for _, nhl_id in starts)
    out = {
        p.nhl_id
        for injury in injury_reads_before(conn, as_of)
        if injury.is_out
        for p in [goalies.find(injury.player_name)[0]]
        if p is not None
    }
    order = {nhl_id: rank for rank, (_, nhl_id) in enumerate(reversed(starts))}
    ranked = sorted(
        (nhl_id for nhl_id in counts if nhl_id not in out),
        key=lambda nhl_id: (-counts[nhl_id], -order[nhl_id]),
    )
    if not ranked:
        return None
    player = goalies.catalog.resolve(ranked[0])
    return GoalieStart(player, StarterStatus.UNKNOWN, StarterSource.MODEL_GUESS, as_of)


def resolve_goalie(
    conn: sqlite3.Connection,
    game: Game,
    team: str,
    as_of: datetime,
    *,
    use_reads: bool,
    use_boxscore: bool = True,
    catalog: Catalog | None = None,
) -> tuple[GoalieStart | None, tuple[MissingInput, ...]]:
    """Return the goalie for ``team`` in ``game`` at ``as_of``, and what was missing.

    The order is: a goalie on ``game``; the boxscore starter when the game has started;
    the earliest confirmed read; the newest likely read; the goalie with the most starts
    in the last ``STARTER_WINDOW`` games. With ``use_reads`` false, only the first two
    and the last apply. With ``use_boxscore`` false, the boxscore of a game that has
    started is ignored, so a backtest can ask what a morning guess would have been.
    A caller that resolves many games passes one ``catalog`` to reuse.
    """
    given = game.home_goalie if team == game.home else game.away_goalie
    if given is not None:
        return given, ()
    catalog = player_catalog(conn) if catalog is None else catalog
    if use_boxscore and as_of >= game.start:
        started = boxscore_starter(conn, game, team, catalog)
        if started is not None:
            note = "prediction made after puck drop; the goalie is the boxscore starter"
            return started, (MissingInput(MissingKind.LATE_RUN, team, note),)
    goalies = _Goalies(catalog, team)
    notes: list[MissingInput] = []
    if use_reads:
        chosen, notes = _from_reads(
            starter_reads_before(conn, game.game_id, team, as_of), goalies, team
        )
        if chosen is not None:
            return chosen, tuple(notes)
    guessed = _guess(conn, goalies, team, as_of)
    why = "no source names the starter; the goalie with the most recent starts is used"
    if guessed is None:
        why = "no source names the starter, and the store has no goalie start for the team"
    return guessed, (*notes, _unknown(team, why))
