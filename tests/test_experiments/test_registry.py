"""Tests for the experiment registry module.

Covers:
- registry_dir and results_dir (paths inside the repository root)
- list_records (empty, with records, non-record files skipped, missing directory)
- get_record (valid, not found)
- record_exists (present, absent)
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
    record_exists,
    register_record,
    registry_dir,
    results_dir,
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


class TestPaths:
    """Test the registry and results paths."""

    def test_registry_dir_is_under_the_root(self, repo_root: Path):
        """The registry directory is the experiments directory of the repository."""
        assert registry_dir(repo_root) == repo_root / "experiments"

    def test_results_dir_is_under_the_registry(self, repo_root: Path):
        """The results directory is inside the registry directory."""
        assert results_dir(repo_root) == repo_root / "experiments" / "results"

    def test_list_records_is_empty_when_the_directory_is_missing(self, tmp_path: Path):
        """A repository with no registry directory has no records, not an error."""
        assert list_records(tmp_path) == []


class TestListRecords:
    """Test list_records."""

    def test_list_records_empty(self, repo_root: Path):
        """List returns an empty list when no records are registered."""
        assert list_records(repo_root) == []

    def test_list_records_sorted(self, registry_dir: Path, repo_root: Path):
        """List returns record IDs sorted by name."""
        (registry_dir / "0002-second.json").write_text("{}", encoding="utf-8")
        (registry_dir / "0001-first.json").write_text("{}", encoding="utf-8")
        assert list_records(repo_root) == ["0001-first", "0002-second"]

    def test_list_records_skips_non_record_files(self, registry_dir: Path, repo_root: Path):
        """A file that is not a record id is not a record."""
        (registry_dir / "0001-first.json").write_text("{}", encoding="utf-8")
        (registry_dir / "notes.json").write_text("{}", encoding="utf-8")
        (registry_dir / "0001-first.txt").write_text("", encoding="utf-8")
        assert list_records(repo_root) == ["0001-first"]


class TestGetRecord:
    """Test get_record and record_exists."""

    def test_get_record_returns_the_record(self, registry_dir: Path, repo_root: Path):
        """get_record loads a registered record."""
        record = _make_record()
        register_record(record, repo_root)
        loaded = get_record(record.id, repo_root)
        assert loaded.id == record.id
        assert loaded.candidate_features == ("xg_form",)

    def test_get_record_not_found(self, repo_root: Path):
        """get_record says the record is not found, not that the file cannot be read."""
        with pytest.raises(HockeyModelError, match="not found"):
            get_record("0001-missing", repo_root)

    def test_record_exists_reports_presence(self, registry_dir: Path, repo_root: Path):
        """record_exists is True for a written record and False for an absent one."""
        (registry_dir / "0003-present.json").write_text("{}", encoding="utf-8")
        assert record_exists("0003-present", repo_root) is True
        assert record_exists("0004-absent", repo_root) is False


class TestFindRecordById:
    """Test find_record_by_id."""

    def test_find_record_not_found(self, repo_root: Path):
        """find_record_by_id returns None when the record does not exist."""
        assert find_record_by_id("0001-missing", repo_root) is None

    def test_find_record_corrupt_raises(self, registry_dir: Path, repo_root: Path):
        """find_record_by_id raises when the record file is not valid JSON."""
        (registry_dir / "0007-broken.json").write_text("{not json", encoding="utf-8")
        with pytest.raises(HockeyModelError, match="invalid JSON"):
            find_record_by_id("0007-broken", repo_root)


class TestRegisterRecord:
    """Test register_record."""

    def test_register_new_record(self, registry_dir: Path, repo_root: Path):
        """Registering a new record writes the file."""
        record = _make_record()
        register_record(record, repo_root)
        assert (registry_dir / f"{record.id}.json").exists()

    def test_register_creates_the_registry_directory(self, tmp_path: Path):
        """Registering a record in an empty repository writes the record file."""
        record = _make_record({"id": "0010-new"})
        register_record(record, tmp_path)
        assert (tmp_path / "experiments" / "0010-new.json").exists()

    def test_register_duplicate_id_fails(self, repo_root: Path):
        """Registering the same id twice raises HockeyModelError."""
        register_record(_make_record({"id": "0099-first"}), repo_root)
        second = _make_record({"id": "0099-first", "title": "duplicate"})
        with pytest.raises(HockeyModelError, match="already exists"):
            register_record(second, repo_root)

    def test_register_duplicate_number_fails(self, repo_root: Path):
        """Two records cannot share the registry number."""
        register_record(_make_record({"id": "0099-first"}), repo_root)
        with pytest.raises(HockeyModelError, match="number 0099 is taken"):
            register_record(_make_record({"id": "0099-second"}), repo_root)

    def test_register_bad_id_fails(self, repo_root: Path):
        """An id without the NNNN-slug shape is refused."""
        with pytest.raises(HockeyModelError, match="invalid experiment id"):
            register_record(_make_record({"id": "test-record"}), repo_root)

    def test_register_invalid_record_fails(self, repo_root: Path):
        """A record that fails the schema is refused before it is written."""
        with pytest.raises(HockeyModelError, match="not in"):
            register_record(_make_record({"status": "maybe"}), repo_root)
        assert list_records(repo_root) == []
