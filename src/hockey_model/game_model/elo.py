"""The results-only Elo, ported from sportsbettr's NHL Elo with the market shrink removed.

Constants, update rule, and margin scaling match sportsbettr ``harness/data.py``
(``apply_elo_updates``, ``_elo_expected``, ``_elo_margin_factor``). The model and the
backtest baseline share this code, so a feature cannot win on Elo tuning alone.
"""

import math
from collections.abc import Iterable

from hockey_model.sources.nhl import GameRow
from hockey_model.sources.teams import franchise

ELO_INITIAL = 1500.0
ELO_K = 8.0
ELO_HOME_ADV = 28.0


def elo_expected(home: float, away: float) -> float:
    """Return the home win chance for two ratings, with the home advantage."""
    return 1.0 / (1.0 + 10.0 ** ((away - home - ELO_HOME_ADV) / 400.0))


class EloBook:
    """The ratings of all teams. A team starts at ``ELO_INITIAL`` on its first game."""

    def __init__(self) -> None:
        self._ratings: dict[str, float] = {}

    def rating(self, team: str) -> float:
        """Return the rating of the franchise of ``team``."""
        return self._ratings.get(franchise(team), ELO_INITIAL)

    def home_win_chance(self, home: str, away: str) -> float:
        """Return the home win chance from the current ratings."""
        return elo_expected(self.rating(home), self.rating(away))

    def update(self, game: GameRow) -> None:
        """Move both ratings by the result of a final game."""
        if not game.is_final or game.home_score is None or game.away_score is None:
            raise ValueError(
                f"update Elo with game {game.game_id}: the game is not final (state "
                f"{game.state!r}); pass final games only"
            )
        if game.home_score == game.away_score:
            raise ValueError(
                f"update Elo with game {game.game_id}: the score is tied "
                f"{game.home_score}-{game.away_score}; an NHL game has a winner"
            )
        expected = self.home_win_chance(game.home, game.away)
        actual = 1.0 if game.home_score > game.away_score else 0.0
        margin = math.log(1 + abs(game.home_score - game.away_score))
        delta = ELO_K * (actual - expected) * margin
        self._ratings[franchise(game.home)] = self.rating(game.home) + delta
        self._ratings[franchise(game.away)] = self.rating(game.away) - delta


def replay(games: Iterable[GameRow]) -> EloBook:
    """Return the book after ``games``, which must be in start order."""
    book = EloBook()
    for game in games:
        book.update(game)
    return book
