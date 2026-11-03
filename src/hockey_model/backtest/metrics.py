"""Scores for win probabilities, and a block bootstrap for their differences."""

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass

# A probability is held inside [PROB_FLOOR, 1 - PROB_FLOOR] before a log, so one extreme
# miss gives a large finite loss, not infinity.
PROB_FLOOR = 1e-6
CALIBRATION_BINS = 10
BOOTSTRAP_RESAMPLES = 1000
BOOTSTRAP_SEED = 0
# Games of one night share goalies and teams, so a block is one night's slate. The busiest
# NHL night has 16 games. The lag-1 autocorrelation of a per-game loss difference is near
# zero, so a longer block would add code and no width.
MIN_BLOCK_LENGTH = 16
_LOW_PERCENTILE = 0.05
_HIGH_PERCENTILE = 0.95


@dataclass(frozen=True, slots=True)
class CalibrationBin:
    """The games whose predicted chance falls in one bin."""

    low: float
    high: float
    count: int
    mean_prob: float | None
    win_rate: float | None


def _check(probs: Sequence[float], wins: Sequence[bool]) -> None:
    if not probs:
        raise ValueError("score probabilities: the list is empty; pass at least one game")
    if len(probs) != len(wins):
        raise ValueError(
            f"score probabilities: {len(probs)} probabilities but {len(wins)} results; "
            "pass one each"
        )
    for value in probs:
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise ValueError(f"score probabilities: {value!r} is not a probability in [0, 1]")


def per_game_log_loss(probs: Sequence[float], wins: Sequence[bool]) -> list[float]:
    """Return the log loss of each game."""
    _check(probs, wins)
    losses = []
    for value, win in zip(probs, wins, strict=True):
        clamped = min(max(value, PROB_FLOOR), 1.0 - PROB_FLOOR)
        losses.append(-math.log(clamped if win else 1.0 - clamped))
    return losses


def log_loss(probs: Sequence[float], wins: Sequence[bool]) -> float:
    """Return the mean log loss. Lower is better."""
    losses = per_game_log_loss(probs, wins)
    return sum(losses) / len(losses)


def brier(probs: Sequence[float], wins: Sequence[bool]) -> float:
    """Return the mean squared error of the probabilities. Lower is better."""
    _check(probs, wins)
    return sum((p - (1.0 if w else 0.0)) ** 2 for p, w in zip(probs, wins, strict=True)) / len(
        probs
    )


def calibration(probs: Sequence[float], wins: Sequence[bool]) -> tuple[CalibrationBin, ...]:
    """Return ten equal bins of predicted chance, with the share of games won in each."""
    _check(probs, wins)
    members: list[list[tuple[float, bool]]] = [[] for _ in range(CALIBRATION_BINS)]
    for value, win in zip(probs, wins, strict=True):
        members[min(int(value * CALIBRATION_BINS), CALIBRATION_BINS - 1)].append((value, win))
    result = []
    for index, games in enumerate(members):
        low, high = index / CALIBRATION_BINS, (index + 1) / CALIBRATION_BINS
        if games:
            mean_prob = sum(p for p, _ in games) / len(games)
            win_rate = sum(w for _, w in games) / len(games)
            result.append(CalibrationBin(low, high, len(games), mean_prob, win_rate))
        else:
            result.append(CalibrationBin(low, high, 0, None, None))
    return tuple(result)


def block_bootstrap_mean_ci(values: Sequence[float]) -> tuple[float, float]:
    """Return the 5th and 95th percentile of the mean over block resamples.

    ``values`` must be in game start order. Blocks are runs of consecutive games, because
    games on one night share teams and goalies.
    """
    if not values:
        raise ValueError("bootstrap the mean: the list is empty; pass at least one value")
    if not all(math.isfinite(v) for v in values):
        raise ValueError("bootstrap the mean: a value is not finite; check the scores")
    count = len(values)
    # One night's slate, and no more than the whole series.
    length = min(count, MIN_BLOCK_LENGTH)
    rng = random.Random(BOOTSTRAP_SEED)
    means = []
    for _ in range(BOOTSTRAP_RESAMPLES):
        total = 0.0
        taken = 0
        while taken < count:
            start = rng.randrange(count - length + 1)
            piece = values[start : start + length][: count - taken]
            total += sum(piece)
            taken += len(piece)
        means.append(total / count)
    means.sort()
    return means[int(_LOW_PERCENTILE * BOOTSTRAP_RESAMPLES)], means[
        int(_HIGH_PERCENTILE * BOOTSTRAP_RESAMPLES)
    ]
