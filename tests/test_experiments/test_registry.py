"""Tests for the experiment registry module.

Covers:
- list_records (empty, with records, schema files skipped)
- get_record (valid, not found)
- find_record_by_id (valid, not found, corrupt file)
- register_record (new, duplicate id, duplicate number, bad id, invalid record)
"""

from pathlib import Path

import pytest

from hockey_model.experiments.models import ExperimentRecord, HockeyModelError
from hockey_model.experiments.registry import (
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
    "candidate_features": ["xg_form"],
    "look_number": 1,
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

    def test_list_records_empty(self, registry_dir: Path):
        """List returns an empty list when no records are registered."""
        assert list_records() == []

    def test_list_records_sorted(self, registry_dir: Path):
        """List returns record IDs sorted by name."""
        (registry_dir / "0002-second.json").write_text("{}", encoding="utf-8")
        (registry_dir / "0001-first.json").write_text("{}", encoding="utf-8")
        assert list_records() == ["0001-first", "0002-second"]

    def test_list_records_skips_schema_files(self, registry_dir: Path):
        """Schema files in the registry are not records."""
        (registry_dir / "0001-first.json").write_text("{}", encoding="utf-8")
        (registry_dir / "schema.json").write_text("{}", encoding="utf-8")
        (registry_dir / "check_output.schema.json").write_text("{}", encoding="utf-8")
        assert list_records() == ["0001-first"]


class TestGetRecord:
    """Test get_record."""

    def test_get_record_returns_the_record(self, registry_dir: Path):
        """get_record loads a registered record."""
        record = _make_record()
        register_record(record)
        loaded = get_record(record.id)
        assert loaded.id == record.id
        assert loaded.candidate_features == ("xg_form",)

    def test_get_record_not_found(self, registry_dir: Path):
        """get_record says the record is not found, not that the file cannot be read."""
        with pytest.raises(HockeyModelError, match="not found"):
            get_record("0001-missing")


class TestFindRecordById:
    """Test find_record_by_id."""

    def test_find_record_not_found(self, registry_dir: Path):
        """find_record_by_id returns None when the record does not exist."""
        assert find_record_by_id("0001-missing") is None

    def test_find_record_corrupt_raises(self, registry_dir: Path):
        """find_record_by_id raises when the record file is not valid JSON."""
        (registry_dir / "0007-broken.json").write_text("{not json", encoding="utf-8")
        with pytest.raises(HockeyModelError, match="invalid JSON"):
            find_record_by_id("0007-broken")


class TestRegisterRecord:
    """Test register_record."""

    def test_register_new_record(self, registry_dir: Path):
        """Registering a new record writes the file."""
        record = _make_record()
        register_record(record)
        assert (registry_dir / f"{record.id}.json").exists()

    def test_register_duplicate_id_fails(self, registry_dir: Path):
        """Registering the same id twice raises HockeyModelError."""
        register_record(_make_record({"id": "0099-first"}))
        second = _make_record({"id": "0099-first", "title": "duplicate"})
        with pytest.raises(HockeyModelError, match="already exists"):
            register_record(second)

    def test_register_duplicate_number_fails(self, registry_dir: Path):
        """Two records cannot share the registry number."""
        register_record(_make_record({"id": "0099-first"}))
        with pytest.raises(HockeyModelError, match="number 0099 is taken"):
            register_record(_make_record({"id": "0099-second"}))

    def test_register_bad_id_fails(self, registry_dir: Path):
        """An id without the NNNN-slug shape is refused."""
        with pytest.raises(HockeyModelError, match="invalid experiment id"):
            register_record(_make_record({"id": "test-record"}))

    def test_register_invalid_record_fails(self, registry_dir: Path):
        """A record that fails the schema is refused before it is written."""
        with pytest.raises(HockeyModelError, match="not in"):
            register_record(_make_record({"status": "maybe"}))
        assert list_records() == []
