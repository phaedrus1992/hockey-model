"""The imputation share of fit rows, and the refusal above the frozen limit."""

import math

import pytest

from hockey_model.game import DegradedInput, MissingKind
from hockey_model.game_model.features import FeatureRow
from hockey_model.game_model.imputation import (
    IMPUTATION_LIMIT,
    ImputationLimitError,
    check_imputation,
    feature_quality,
    validate_limit,
)


def _row(*imputed: DegradedInput) -> FeatureRow:
    return FeatureRow(
        game_id=1,
        elo_logit=0.0,
        values={},
        missing=(),
        uses_moneypuck=False,
        imputed=imputed,
    )


XG = DegradedInput("xg_form", MissingKind.XG_FORM, ("TOR",))
REST = DegradedInput("rest", MissingKind.REST_UNKNOWN, ("TOR",))


def test_a_row_with_two_reasons_for_one_feature_counts_once() -> None:
    rows = [_row(XG, DegradedInput("xg_form", MissingKind.XG_FORM, ("MTL",)))]
    (quality,) = feature_quality(rows, ["xg_form"])
    assert (quality.imputed, quality.total) == (1, 1)


def test_a_measured_row_is_not_counted() -> None:
    rows = [_row(), _row(XG)]
    (quality,) = feature_quality(rows, ["xg_form"])
    assert (quality.imputed, quality.total, quality.share) == (1, 2, 0.5)


def test_only_selected_features_are_reported() -> None:
    rows = [_row(XG, REST)]
    names = [q.feature for q in feature_quality(rows, ["rest"])]
    assert names == ["rest"]


def test_an_empty_denominator_is_an_error_not_a_zero_share() -> None:
    with pytest.raises(ValueError, match="no rows"):
        feature_quality([], ["xg_form"])


def test_a_share_at_the_limit_passes_and_above_it_is_refused() -> None:
    limit = 0.5
    at_limit = [_row(XG), _row()]
    assert check_imputation(at_limit, ["xg_form"], limit)[0].share == limit
    above = [_row(XG), _row(XG), _row()]
    with pytest.raises(ImputationLimitError, match="xg_form"):
        check_imputation(above, ["xg_form"], limit)


@pytest.mark.parametrize("bad", [0.0, -0.1, 1.5, math.nan, math.inf])
def test_the_limit_must_be_a_share_above_zero_and_at_most_one(bad: float) -> None:
    with pytest.raises(ValueError, match="imputation limit"):
        validate_limit(bad)


def test_the_frozen_limit_is_a_valid_share() -> None:
    assert validate_limit(IMPUTATION_LIMIT) == IMPUTATION_LIMIT
