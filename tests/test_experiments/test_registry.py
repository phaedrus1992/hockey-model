"""Tests for the experiment registry module.

Covers:
- registry_dir and results_dir (paths inside the repository root)
- list_records (empty, with records, non-record files skipped, missing directory)
- get_record and record_exists (valid, not found, malformed id)
- check_record_id and duplicate_numbers
"""

from pathlib import Path

import pytest

from hockey_model.experiments.models import ExperimentRecord, HockeyModelError
from hockey_model.experiments.registry import (
    check_record_id,
    duplicate_numbers,
    get_record,
    list_records,
    record_exists,
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
        """get_record loads a written record."""
        record = ExperimentRecord.from_dict(_VALID_RECORD_DATA)
        record.save(registry_dir / f"{record.id}.json")
        loaded = get_record(record.id, repo_root)
        assert loaded.id == record.id
        assert loaded.candidate_features == ("xg_form",)

    def test_get_record_not_found(self, repo_root: Path):
        """get_record says the record is not found, not that the file cannot be read."""
        with pytest.raises(HockeyModelError, match="not found"):
            get_record("0001-missing", repo_root)

    def test_get_record_refuses_a_path_outside_the_registry(self, repo_root: Path):
        """An id with path parts cannot load a file from outside the registry."""
        (repo_root / "x.json").write_text("{}", encoding="utf-8")
        with pytest.raises(HockeyModelError, match="invalid experiment id"):
            get_record("../x", repo_root)

    def test_record_exists_reports_presence(self, registry_dir: Path, repo_root: Path):
        """record_exists is True for a written record and False for an absent one."""
        (registry_dir / "0003-present.json").write_text("{}", encoding="utf-8")
        assert record_exists("0003-present", repo_root) is True
        assert record_exists("0004-absent", repo_root) is False

    def test_record_exists_refuses_a_malformed_id(self, repo_root: Path):
        """record_exists rejects an id that is not NNNN-slug."""
        with pytest.raises(HockeyModelError, match="invalid experiment id"):
            record_exists("test-record", repo_root)


class TestRecordIds:
    """Test id and number checks."""

    @pytest.mark.parametrize("bad", ["", "1-x", "0001", "0001-", "0001-A", "0001-a/b", "../0001-a"])
    def test_check_record_id_rejects_a_bad_shape(self, bad: str):
        """Only NNNN-slug with a lowercase slug passes."""
        with pytest.raises(HockeyModelError, match="invalid experiment id"):
            check_record_id(bad)

    def test_check_record_id_accepts_a_good_id(self):
        """A four-digit number and a lowercase slug pass."""
        check_record_id("0042-attempt-form")

    def test_duplicate_numbers_lists_each_repeated_number_once(self):
        """Three records on one number report that number one time."""
        ids = ["0001-a", "0002-b", "0001-c", "0001-d", "0002-e", "0003-f"]
        assert duplicate_numbers(ids) == ["0001", "0002"]

    def test_duplicate_numbers_is_empty_for_unique_numbers(self):
        """Unique numbers report nothing."""
        assert duplicate_numbers(["0001-a", "0002-b"]) == []
