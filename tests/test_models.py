"""Tests for model protocols and deterministic fakes."""

import pytest

from hockey_model.models import FixedStatModel, StatModel
from hockey_model.types import MissingProjectionError, Player, Projection, Slot


def _player(canonical_id: str) -> Player:
    return Player(canonical_id, None, None, canonical_id, frozenset({Slot.C}), None)


def test_fixed_model_returns_stored_projection() -> None:
    projection = Projection(point=0.4, low=0.1, high=0.7, level=0.8)
    model = FixedStatModel({("p-a", "goals"): projection})
    assert model.project(_player("p-a"), "goals", 1, 0.8) == projection
    assert isinstance(model, StatModel)


def test_fixed_model_misses_raise_missing_projection() -> None:
    with pytest.raises(MissingProjectionError, match="p-b.*goals"):
        FixedStatModel({}).project(_player("p-b"), "goals", 1, 0.8)
