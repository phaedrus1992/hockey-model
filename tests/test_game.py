"""Tests for the public NHL game input and the game win probability entry point."""

import math
from datetime import UTC, datetime, timedelta, timezone

import pytest
from hypothesis import given
from hypothesis import strategies as st

from hockey_model.game import Game, GamePrediction, MissingKind, game_win_probability
from hockey_model.team_codes import NHL_TEAM_CODES
from hockey_model.types import HockeyModelError, ProbabilityError, Projection

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


def _game(*, game_id: int = 1, away: str = "TOR") -> Game:
    return Game(game_id=game_id, home="CAR", away=away, start=START)


def test_game_rejects_naive_start() -> None:
    with pytest.raises(HockeyModelError, match="timezone"):
        Game(1, "CAR", "TOR", datetime(2026, 1, 1))


def test_game_rejects_same_team() -> None:
    with pytest.raises(HockeyModelError, match="differ"):
        _game(away="CAR")


@pytest.mark.parametrize("game_id", [0, -4])
def test_game_rejects_nonpositive_id(game_id: int) -> None:
    with pytest.raises(HockeyModelError, match="game_id"):
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
    with pytest.raises(HockeyModelError, match="level"):
        game_win_probability(_game(), StubModel(), as_of=START, level=level)


def test_game_win_probability_rejects_naive_as_of() -> None:
    with pytest.raises(HockeyModelError, match="timezone"):
        game_win_probability(_game(), StubModel(), as_of=datetime(2026, 1, 9))


def test_late_prediction_names_missing_late_run() -> None:
    result = game_win_probability(_game(), StubModel(), as_of=START)
    assert [item.kind for item in result.missing] == [MissingKind.LATE_RUN]


def test_pregame_prediction_has_no_late_run_note() -> None:
    result = game_win_probability(_game(), StubModel(), as_of=START - timedelta(seconds=1))
    assert result.missing == ()


def test_game_rejects_non_utc_offset() -> None:
    eastern = timezone(timedelta(hours=-5))
    with pytest.raises(HockeyModelError, match="UTC"):
        Game(1, "CAR", "TOR", datetime(2026, 1, 10, 0, 0, tzinfo=eastern))


def test_game_rejects_same_team_ignoring_padding() -> None:
    with pytest.raises(HockeyModelError, match="differ"):
        Game(1, "CAR", " CAR ", START)


@pytest.mark.parametrize("code", ["BSO", "tor", "TOR ", "XYZ"])
def test_game_rejects_unknown_team_code(code: str) -> None:
    with pytest.raises(HockeyModelError, match=r"unknown NHL team code.*known codes"):
        Game(1, code, "MTL", datetime(2026, 1, 1, tzinfo=UTC))
    with pytest.raises(HockeyModelError, match="unknown NHL team code"):
        Game(1, "MTL", code, datetime(2026, 1, 1, tzinfo=UTC))


_START_ZONES = st.none() | st.just(UTC) | st.timezones() | st.just(timezone(timedelta(0)))


@given(
    game_id=st.integers(min_value=-5, max_value=10),
    home=st.sampled_from(sorted(NHL_TEAM_CODES)) | st.text(max_size=5),
    away=st.sampled_from(sorted(NHL_TEAM_CODES)) | st.text(max_size=5),
    start=st.datetimes(timezones=_START_ZONES),
)
def test_property_game_accepts_exactly_the_valid_inputs(
    game_id: int, home: str, away: str, start: datetime
) -> None:
    valid = (
        game_id > 0
        and home in NHL_TEAM_CODES
        and away in NHL_TEAM_CODES
        and home != away
        and start.tzinfo is not None
        and start.utcoffset() == timedelta(0)
    )
    if valid:
        game = Game(game_id, home, away, start)
        assert (game.home, game.away) == (home, away)
    else:
        with pytest.raises(HockeyModelError):
            Game(game_id, home, away, start)
