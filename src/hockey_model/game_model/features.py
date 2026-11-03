"""The features of one game: Elo plus expected-goals form, goalie form, and rest.

Every feature is the home value minus the away value. A value that cannot be computed is
0.0 and adds a ``MissingInput``, so a missing input never looks like a measured zero.
All history is read as of the earlier of ``as_of`` and the game start.
"""

import math
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from hockey_model.game import Game, GoalieStart, MissingInput, MissingKind
from hockey_model.game_model.elo import EloBook
from hockey_model.game_model.goalies import boxscore_starter, resolve_goalie
from hockey_model.identity import Catalog
from hockey_model.store.reads import (
    mp_goalie_form_before,
    mp_team_form_before,
    player_catalog,
    team_games_before,
)

FEATURES = ("xg_form", "goalie_gsax", "rest")
FORM_WINDOW = 10
GOALIE_WINDOW = 20
REST_CAP_DAYS = 4.0
_DAY = timedelta(days=1)


class GoalieMode(StrEnum):
    """Where the starting goalie comes from."""

    ACTUAL = "actual"  # the boxscore starter, which only a backtest can know
    READS = "reads"  # the source reads, then the estimate: a live prediction
    GUESS = "guess"  # the estimate only, even after puck drop: the cost of a morning guess


@dataclass(frozen=True, slots=True)
class FeatureRow:
    """The model inputs for one game."""

    game_id: int
    elo_logit: float
    values: Mapping[str, float]
    missing: tuple[MissingInput, ...]
    uses_moneypuck: bool


def _logit(probability: float) -> float:
    return math.log(probability / (1.0 - probability))


def _xg_share(rows: list[tuple[float, float]]) -> float | None:
    shares = [made / (made + allowed) for made, allowed in rows if made + allowed > 0]
    return sum(shares) / len(shares) if shares else None


def _xg_form(
    conn: sqlite3.Connection, game: Game, cutoff: datetime
) -> tuple[float, list[MissingInput]]:
    shares: dict[str, float | None] = {}
    for team in (game.home, game.away):
        shares[team] = _xg_share(mp_team_form_before(conn, team, cutoff, FORM_WINDOW))
    missing = [
        MissingInput(MissingKind.XG_FORM, team, "no MoneyPuck games before this game")
        for team, share in shares.items()
        if share is None
    ]
    home, away = shares[game.home], shares[game.away]
    if home is None or away is None:
        return 0.0, missing
    return home - away, missing


def _starter(
    conn: sqlite3.Connection,
    game: Game,
    team: str,
    as_of: datetime,
    mode: GoalieMode,
    catalog: Catalog,
) -> tuple[GoalieStart | None, list[MissingInput]]:
    if mode is GoalieMode.ACTUAL:
        start = boxscore_starter(conn, game, team, catalog)
        if start is not None:
            return start, []
        note = "the game has no boxscore starter"
        return None, [MissingInput(MissingKind.GOALIE_UNKNOWN, team, note)]
    start, notes = resolve_goalie(
        conn,
        game,
        team,
        as_of,
        use_reads=mode is GoalieMode.READS,
        use_boxscore=mode is not GoalieMode.GUESS,
        catalog=catalog,
    )
    return start, list(notes)


def _goalie_gsax(
    conn: sqlite3.Connection,
    game: Game,
    as_of: datetime,
    mode: GoalieMode,
    catalog: Catalog,
) -> tuple[float, list[MissingInput], bool]:
    """Return the home minus away goals saved above expected, the gaps, and MoneyPuck use."""
    cutoff = min(as_of, game.start)
    missing: list[MissingInput] = []
    values: dict[str, float] = {}
    used = False
    for team in (game.home, game.away):
        start, notes = _starter(conn, game, team, as_of, mode, catalog)
        missing.extend(notes)
        values[team] = 0.0
        if start is None:
            continue
        if start.player.nhl_id is None:
            note = f"{start.player.full_name} has no NHL id, so goalie form is not used"
            missing.append(MissingInput(MissingKind.GOALIE_FORM, team, note))
            continue
        rows = mp_goalie_form_before(conn, start.player.nhl_id, cutoff, GOALIE_WINDOW)
        if not rows:
            note = f"no MoneyPuck games for {start.player.full_name} before this game"
            missing.append(MissingInput(MissingKind.GOALIE_FORM, team, note))
            continue
        used = True
        values[team] = sum(xg - goals for xg, goals in rows) / len(rows)
    return values[game.home] - values[game.away], missing, used


def _days_rested(conn: sqlite3.Connection, team: str, start: datetime) -> float | None:
    """Return the days since the team's last game, capped, or ``None`` with no earlier game."""
    previous = team_games_before(conn, team, start, 1)
    if not previous:
        return None
    return min((start - previous[0].start) / _DAY, REST_CAP_DAYS)


def _rest(conn: sqlite3.Connection, game: Game) -> tuple[float, list[MissingInput]]:
    """Return home minus away rest. A team with no earlier game counts as fully rested."""
    days: dict[str, float] = {}
    missing: list[MissingInput] = []
    for team in (game.home, game.away):
        found = _days_rested(conn, team, game.start)
        if found is None:
            note = f"no earlier game in the store; {REST_CAP_DAYS:g} days of rest is used"
            missing.append(MissingInput(MissingKind.REST_UNKNOWN, team, note))
        days[team] = REST_CAP_DAYS if found is None else found
    return days[game.home] - days[game.away], missing


def build_features(
    conn: sqlite3.Connection,
    game: Game,
    as_of: datetime,
    elo: EloBook,
    *,
    goalie_mode: GoalieMode,
    catalog: Catalog | None = None,
) -> FeatureRow:
    """Return the features of ``game`` as known at ``as_of``.

    ``elo`` must hold the ratings after every game that was over at the cutoff.
    A caller that builds many rows passes one ``catalog`` to reuse.
    """
    catalog = player_catalog(conn) if catalog is None else catalog
    cutoff = min(as_of, game.start)
    xg_form, xg_missing = _xg_form(conn, game, cutoff)
    gsax, goalie_missing, goalie_used = _goalie_gsax(conn, game, as_of, goalie_mode, catalog)
    rest, rest_missing = _rest(conn, game)
    form_used = len(xg_missing) < 2  # noqa: PLR2004  # two teams, so fewer than two gaps
    return FeatureRow(
        game_id=game.game_id,
        elo_logit=_logit(elo.home_win_chance(game.home, game.away)),
        values={"xg_form": xg_form, "goalie_gsax": gsax, "rest": rest},
        missing=(*xg_missing, *goalie_missing, *rest_missing),
        uses_moneypuck=form_used or goalie_used,
    )
