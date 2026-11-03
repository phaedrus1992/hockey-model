"""Tests for the backtest metrics."""

import math
import random

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from hockey_model.backtest.metrics import (
    BOOTSTRAP_RESAMPLES,
    MIN_BLOCK_LENGTH,
    PROB_FLOOR,
    block_bootstrap_mean_ci,
    block_length,
    brier,
    calibration,
    log_loss,
    per_game_log_loss,
)


def test_log_loss_of_a_coin_flip() -> None:
    assert log_loss([0.5], [True]) == pytest.approx(math.log(2))
    assert log_loss([0.5, 0.5], [True, False]) == pytest.approx(math.log(2))


def test_log_loss_is_the_mean_of_the_games() -> None:
    expected = (-math.log(0.8) - math.log(0.7)) / 2
    assert log_loss([0.8, 0.3], [True, False]) == pytest.approx(expected)


def test_a_zero_probability_on_a_win_is_finite() -> None:
    value = log_loss([0.0], [True])
    assert math.isfinite(value)
    assert value == pytest.approx(13.815510557964274)
    assert PROB_FLOOR == 1e-6


def test_a_certain_probability_on_a_loss_is_finite() -> None:
    assert math.isfinite(log_loss([1.0], [False]))


def test_brier_scores() -> None:
    assert brier([1.0], [True]) == 0.0
    assert brier([0.0], [True]) == 1.0
    assert brier([0.5, 0.5], [True, False]) == pytest.approx(0.25)


@pytest.mark.parametrize("score", [log_loss, brier, calibration])
def test_length_mismatch_raises(score) -> None:
    with pytest.raises(ValueError, match="2 probabilities but 1 results"):
        score([0.5, 0.5], [True])


@pytest.mark.parametrize("score", [log_loss, brier, calibration, per_game_log_loss])
def test_empty_input_raises(score) -> None:
    with pytest.raises(ValueError, match="empty"):
        score([], [])


@pytest.mark.parametrize("bad", [float("nan"), -0.1, 1.1, float("inf")])
def test_a_non_probability_raises(bad: float) -> None:
    with pytest.raises(ValueError, match="not a probability"):
        log_loss([bad], [True])


def test_calibration_bins() -> None:
    bins = calibration([0.05, 0.95, 0.96], [False, True, True])
    assert len(bins) == 10
    assert (bins[0].count, bins[0].win_rate) == (1, 0.0)
    assert (bins[9].count, bins[9].win_rate) == (2, 1.0)
    assert bins[9].mean_prob == pytest.approx(0.955)
    assert (bins[0].low, bins[0].high) == (0.0, 0.1)


def test_calibration_puts_one_in_the_last_bin() -> None:
    assert calibration([1.0], [True])[9].count == 1
    assert calibration([0.0], [False])[0].count == 1


def test_empty_calibration_bins_have_nan_means() -> None:
    bins = calibration([0.5], [True])
    assert bins[0].count == 0
    assert math.isnan(bins[0].mean_prob)
    assert math.isnan(bins[0].win_rate)


def test_bootstrap_of_a_constant_list() -> None:
    assert block_bootstrap_mean_ci([0.25] * 100) == pytest.approx((0.25, 0.25))


def test_bootstrap_is_repeatable() -> None:
    values = [math.sin(i) for i in range(200)]
    assert block_bootstrap_mean_ci(values) == block_bootstrap_mean_ci(values)


def test_bootstrap_rejects_an_empty_list() -> None:
    with pytest.raises(ValueError, match="empty"):
        block_bootstrap_mean_ci([])


def test_bootstrap_rejects_a_non_finite_value() -> None:
    with pytest.raises(ValueError, match="not finite"):
        block_bootstrap_mean_ci([0.1, float("nan")])


def test_bootstrap_interval_contains_the_mean_of_a_large_sample() -> None:
    values = [0.1 * ((i * 7) % 5 - 2) + 0.02 for i in range(400)]
    low, high = block_bootstrap_mean_ci(values)
    mean = sum(values) / len(values)
    assert low < mean < high
    assert high - low < 0.1


def test_bootstrap_interval_is_about_1_645_standard_errors_wide() -> None:
    rng = random.Random(1)
    values = [rng.gauss(0.0, 1.0) for _ in range(1600)]
    low, high = block_bootstrap_mean_ci(values)
    mean = sum(values) / len(values)
    assert 0.02 < high - mean < 0.07
    assert 0.02 < mean - low < 0.07


def test_bootstrap_of_a_clearly_negative_mean_is_below_zero() -> None:
    values = [-0.05 + 0.01 * ((i * 7) % 5 - 2) for i in range(500)]
    assert block_bootstrap_mean_ci(values)[1] < 0


def test_bootstrap_of_a_zero_mean_straddles_zero() -> None:
    values = [0.1 * ((i * 7) % 5 - 2) for i in range(500)]
    low, high = block_bootstrap_mean_ci(values)
    assert low < 0 < high


def test_blocks_are_wider_than_one_night() -> None:
    assert block_length([0.1, -0.1] * 200) == MIN_BLOCK_LENGTH
    assert block_length([0.1, -0.1, 0.3]) == 3


def test_block_length_grows_with_positive_autocorrelation() -> None:
    drift = [math.sin(i / 40) for i in range(2000)]
    assert block_length(drift) > MIN_BLOCK_LENGTH
    assert block_length(drift) <= len(drift)


def test_a_short_series_uses_one_block_of_its_own_size() -> None:
    low, high = block_bootstrap_mean_ci([0.1, 0.2, 0.3])
    assert 0.1 <= low <= high <= 0.3


def test_the_number_of_resamples() -> None:
    assert BOOTSTRAP_RESAMPLES == 1000


@settings(max_examples=30, deadline=None)
@given(st.lists(st.floats(min_value=-10, max_value=10), min_size=1, max_size=60))
def test_bootstrap_interval_is_ordered_and_inside_the_data(values: list[float]) -> None:
    low, high = block_bootstrap_mean_ci(values)
    assert low <= high
    assert min(values) - 1e-9 <= low
    assert high <= max(values) + 1e-9


@given(
    st.lists(st.floats(min_value=0, max_value=1), min_size=1, max_size=50),
    st.data(),
)
def test_scores_are_non_negative(probs: list[float], data: st.DataObject) -> None:
    wins = data.draw(st.lists(st.booleans(), min_size=len(probs), max_size=len(probs)))
    assert log_loss(probs, wins) >= 0
    assert 0 <= brier(probs, wins) <= 1
    assert sum(b.count for b in calibration(probs, wins)) == len(probs)
