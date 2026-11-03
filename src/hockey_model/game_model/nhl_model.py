"""The NHL game win model: Elo plus fitted features. It reads the store and fetches nothing."""

import math
import sqlite3
from datetime import datetime

from hockey_model.game import Game, GamePrediction, MissingInput, MissingKind
from hockey_model.game_model.elo import replay
from hockey_model.game_model.features import FORM_WINDOW, GoalieMode, build_features
from hockey_model.game_model.logistic import LogisticFit, predict_logistic
from hockey_model.sources.moneypuck import MONEYPUCK_CREDIT
from hockey_model.sources.teams import franchise
from hockey_model.store.reads import final_games_before, mp_team_form_before, team_games_before
from hockey_model.store.source_reads import stale_sources
from hockey_model.types import Projection

# Goals per team and game when a team has no games in the store. The NHL average is near 3.
LEAGUE_GOALS = 3.0
_MIN_RATE = 0.1


def _poisson_quantile(rate: float, probability: float) -> int:
    """Return the smallest count whose cumulative Poisson chance reaches ``probability``."""
    term = math.exp(-rate)
    total = term
    count = 0
    while total < probability and count < 1000:  # noqa: PLR2004  # a guard against a bad rate
        count += 1
        term *= rate / count
        total += term
    return count


def _projection(rate: float, level: float) -> Projection:
    rate = max(rate, _MIN_RATE)
    low = _poisson_quantile(rate, (1.0 - level) / 2.0)
    high = _poisson_quantile(rate, (1.0 + level) / 2.0)
    return Projection(rate, min(float(low), rate), max(float(high), rate), level)


def _goals_for_and_against(
    conn: sqlite3.Connection, team: str, cutoff: datetime
) -> tuple[list[float], list[float], bool]:
    """Return the goals a team's games made and allowed, and whether xG was used."""
    rows = mp_team_form_before(conn, team, cutoff, FORM_WINDOW)
    if rows:
        return [made for made, _ in rows], [allowed for _, allowed in rows], True
    scored: list[float] = []
    allowed: list[float] = []
    for game in team_games_before(conn, team, cutoff, FORM_WINDOW):
        mine_home = franchise(game.home) == franchise(team)
        home_score, away_score = game.home_score or 0, game.away_score or 0
        scored.append(home_score if mine_home else away_score)
        allowed.append(away_score if mine_home else home_score)
    return scored, allowed, False


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


class NhlGameModel:
    """Predict a game from the store, as known at the prediction time."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        fit: LogisticFit,
        goalie_mode: GoalieMode = GoalieMode.READS,
    ) -> None:
        self._conn = conn
        self._fit = fit
        self._mode = goalie_mode

    def _expected_goals(
        self, game: Game, cutoff: datetime
    ) -> tuple[float, float, list[MissingInput]]:
        home_for, home_against, _ = _goals_for_and_against(self._conn, game.home, cutoff)
        away_for, away_against, _ = _goals_for_and_against(self._conn, game.away, cutoff)
        notes: list[MissingInput] = []
        rates: list[float] = []
        for team, own, theirs in (
            (game.home, home_for, away_against),
            (game.away, away_for, home_against),
        ):
            attack, defence = _mean(own), _mean(theirs)
            if attack is None or defence is None:
                note = f"no games before this game; {LEAGUE_GOALS} goals is used"
                notes.append(MissingInput(MissingKind.XG_FORM, team, note))
            rates.append(
                LEAGUE_GOALS if attack is None or defence is None else (attack + defence) / 2
            )
        return rates[0], rates[1], notes

    def predict(self, game: Game, as_of: datetime, level: float) -> GamePrediction:
        """Return the win chances and expected goals of ``game`` as known at ``as_of``."""
        cutoff = min(as_of, game.start)
        elo = replay(final_games_before(self._conn, cutoff))
        row = build_features(self._conn, game, as_of, elo, goalie_mode=self._mode)
        home_win = predict_logistic(self._fit, row)
        home_rate, away_rate, goal_notes = self._expected_goals(game, cutoff)
        missing = [*row.missing, *goal_notes]
        missing.extend(
            MissingInput(MissingKind.STALE_SOURCE, None, f"the newest read of {source} failed")
            for source in stale_sources(self._conn, as_of)
        )
        credits = (MONEYPUCK_CREDIT,) if row.uses_moneypuck else ()
        return GamePrediction(
            home_win=home_win,
            away_win=1.0 - home_win,
            home_goals=_projection(home_rate, level),
            away_goals=_projection(away_rate, level),
            missing=tuple(missing),
            credits=credits,
        )
