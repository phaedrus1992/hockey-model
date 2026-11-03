"""Tests for the public NHL game input and the game win probability entry point."""

import math
from datetime import UTC, datetime, timedelta

import pytest

from hockey_model.game import Game, GamePrediction, game_win_probability
from hockey_model.types import ProbabilityError, Projection

START = datetime(2026, 1, 10, 0, 0, tzinfo=UTC)


def _projection(point: float) -> Projection:
    return Projection(point=point, low=point - 1.0, high=point + 1.0, level=0.8)


class StubModel:
    """A deterministic model that returns fixed win probabilities."""

    def __init__(
        self,
        home_win: float = 0.6,
        away_win: float = 0.4,
        made_after_start: bool = False,
    ) -> None:
        self.home_win = home_win
        self.away_win = away_win
        self.made_after_start = made_after_start
        self.seen_as_of: datetime | None = None

    def predict(self, game: Game, as_of: datetime, level: float) -> GamePrediction:
        del level
        self.seen_as_of = as_of
        return GamePrediction(
            home_win=self.home_win,
            away_win=self.away_win,
            home_goals=_projection(3.0),
            away_goals=_projection(2.5),
            missing=(),
            credits=(),
            made_after_start=self.made_after_start,
        )


def _game(*, game_id: int = 1, away: str = "MTL") -> Game:
    return Game(game_id=game_id, home="TOR", away=away, start=START)


def test_game_rejects_naive_start() -> None:
    with pytest.raises(ValueError, match="timezone"):
        Game(1, "TOR", "MTL", datetime(2026, 1, 1))


def test_game_rejects_same_team() -> None:
    with pytest.raises(ValueError, match="differ"):
        _game(away="TOR")


@pytest.mark.parametrize("game_id", [0, -4])
def test_game_rejects_nonpositive_id(game_id: int) -> None:
    with pytest.raises(ValueError, match="game_id"):
        _game(game_id=game_id)


def test_game_win_probability_returns_model_result() -> None:
    result = game_win_probability(_game(), StubModel(0.6, 0.4), as_of=START)
    assert result.home_win == 0.6
    assert result.away_win == 0.4


@pytest.mark.parametrize(
    ("as_of", "expected"),
    [
        (START - timedelta(seconds=1), False),
        (START, True),
        (START + timedelta(seconds=1), True),
    ],
)
@pytest.mark.parametrize("model_says", [True, False])
def test_made_after_start_flag_ignores_model(
    as_of: datetime, expected: bool, model_says: bool
) -> None:
    model = StubModel(made_after_start=model_says)
    result = game_win_probability(_game(), model, as_of=as_of)
    assert result.made_after_start is expected


def test_game_win_probability_defaults_as_of_to_now() -> None:
    model = StubModel()
    game_win_probability(_game(), model)
    assert model.seen_as_of is not None
    assert model.seen_as_of.tzinfo is not None
    delta = abs((datetime.now(UTC) - model.seen_as_of).total_seconds())
    assert delta < 5


def test_game_win_probability_rejects_bad_sum() -> None:
    with pytest.raises(ProbabilityError, match="sum to 1.0"):
        game_win_probability(_game(), StubModel(0.6, 0.5), as_of=START)


def test_game_win_probability_rejects_nan() -> None:
    with pytest.raises(ProbabilityError):
        game_win_probability(_game(), StubModel(math.nan, 0.4), as_of=START)


@pytest.mark.parametrize("level", [0.0, 1.0])
def test_game_win_probability_rejects_bad_level(level: float) -> None:
    with pytest.raises(ValueError, match="level"):
        game_win_probability(_game(), StubModel(), as_of=START, level=level)


def test_game_win_probability_rejects_naive_as_of() -> None:
    with pytest.raises(ValueError, match="timezone"):
        game_win_probability(_game(), StubModel(), as_of=datetime(2026, 1, 9))
