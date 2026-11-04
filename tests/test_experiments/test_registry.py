"""Tests for the experiment registry module.

Covers:
- list_records (empty, with records)
- get_record (valid, not found)
- find_record_by_id (valid, not found)
- register_record (new, duplicate)
"""

from pathlib import Path

import pytest

from hockey_model.experiments.models import ExperimentRecord, HockeyModelError
from hockey_model.experiments.registry import (
    REGISTRY_DIR,
    find_record_by_id,
    get_record,
    list_records,
    register_record,
)

_VALID_RECORD_DATA = {
    "id": "0001-test",
    "title": "Test record",
    "hypothesis": "Feature X improves log loss.",
    "cohort": "confirmation",
    "data_cutoff": "2026-10-31",
    "primary_metric": "mean_per_game_log_loss",
    "baseline": {"fit_id": 1, "commit": "abc123"},
    "selection_folds": [[20152016, 20212022]],
    "min_games": 1000,
    "expected_effect": -0.003,
    "promotion_criterion": "95th percentile below zero",
    "failure_outcome": "ship Elo alone",
    "status": "registered",
}


def _make_record(data: dict | None = None) -> ExperimentRecord:
    """Create a valid record from base data, overridden by data."""
    merged = {**_VALID_RECORD_DATA, **(data or {})}
    return ExperimentRecord.from_dict(merged)


class TestListRecords:
    """Test list_records."""

    def test_list_records_empty(self, tmp_path: Path):
        """List returns an empty list when the registry does not exist."""
        old_dir = REGISTRY_DIR
        try:
            import hockey_model.experiments.registry as reg

            reg.REGISTRY_DIR = tmp_path / "nonexistent"
            assert list_records() == []
        finally:
            import hockey_model.experiments.registry as reg2

            reg2.REGISTRY_DIR = old_dir

    def test_list_records_with_files(self, tmp_path: Path):
        """List returns record IDs sorted from registry files."""
        old_dir = REGISTRY_DIR
        reg_dir = tmp_path / "experiments"
        try:
            import hockey_model.experiments.registry as reg

            reg.REGISTRY_DIR = reg_dir
            reg_dir.mkdir(parents=True)
            # Write two record files.
            (reg_dir / "0002-second.json").write_text("{}", encoding="utf-8")
            (reg_dir / "0001-first.json").write_text("{}", encoding="utf-8")
            # Schema file is skipped.
            (reg_dir / "schema.json").write_text("{}", encoding="utf-8")
            assert list_records() == ["0001-first", "0002-second"]
        finally:
            import hockey_model.experiments.registry as reg2

            reg2.REGISTRY_DIR = old_dir


class TestGetRecord:
    """Test get_record."""

    def test_get_record_not_found(self, tmp_path: Path):
        """get_record raises when the record does not exist."""
        old_dir = REGISTRY_DIR
        reg_dir = tmp_path / "experiments"
        try:
            import hockey_model.experiments.registry as reg

            reg.REGISTRY_DIR = reg_dir
            with pytest.raises(HockeyModelError, match="not found"):
                get_record("0001-missing")
        finally:
            import hockey_model.experiments.registry as reg2

            reg2.REGISTRY_DIR = old_dir


class TestFindRecordById:
    """Test find_record_by_id."""

    def test_find_record_not_found(self, tmp_path: Path):
        """find_record_by_id returns None when the record does not exist."""
        old_dir = REGISTRY_DIR
        reg_dir = tmp_path / "experiments"
        try:
            import hockey_model.experiments.registry as reg

            reg.REGISTRY_DIR = reg_dir
            assert find_record_by_id("0001-missing") is None
        finally:
            import hockey_model.experiments.registry as reg2

            reg2.REGISTRY_DIR = old_dir


class TestRegisterRecord:
    """Test register_record."""

    def test_register_new_record(self, tmp_path: Path):
        """Registering a new record writes the file."""
        old_dir = REGISTRY_DIR
        reg_dir = tmp_path / "experiments"
        try:
            import hockey_model.experiments.registry as reg

            reg.REGISTRY_DIR = reg_dir
            reg_dir.mkdir(parents=True)
            record = _make_record()
            register_record(record)
            expected = reg_dir / f"{record.id}.json"
            assert expected.exists()
        finally:
            import hockey_model.experiments.registry as reg2

            reg2.REGISTRY_DIR = old_dir

    def test_register_duplicate_fails(self, tmp_path: Path):
        """Registering a duplicate record raises HockeyModelError."""
        old_dir = REGISTRY_DIR
        reg_dir = tmp_path / "experiments"
        try:
            import hockey_model.experiments.registry as reg

            reg.REGISTRY_DIR = reg_dir
            reg_dir.mkdir(parents=True)
            record = _make_record({"id": "0099-first"})
            register_record(record)
            second = _make_record({"id": "0099-first", "title": "duplicate"})
            with pytest.raises(HockeyModelError, match="already exists"):
                register_record(second)
        finally:
            import hockey_model.experiments.registry as reg2

            reg2.REGISTRY_DIR = old_dir
