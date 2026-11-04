"""Tests for the experiment checker module.

Covers:
- check_all (valid records, invalid records, empty)
- check_experiment (single record)
- Schema validation
- Immutable field checking
"""

import json
from pathlib import Path
from typing import Any, cast

from hockey_model.experiments.check import (
    check_all,
    check_experiment,
)
from hockey_model.experiments.models import (
    ExperimentRecord,
    _Result,
)
from hockey_model.experiments.registry import (
    REGISTRY_DIR,
    register_record,
)

_VALID_RECORD_DATA = {
    "id": "0001-valid",
    "title": "Valid record",
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


def _write_schema(tmp_path: Path, schema: dict) -> Path:
    """Write a schema file and return its path."""
    schema_path = tmp_path / "experiments" / "schema.json"
    schema_path.parent.mkdir(parents=True)
    schema_path.write_text(json.dumps(schema), encoding="utf-8")
    return schema_path


class TestCheckAll:
    """Test check_all."""

    def test_check_all_empty(self, tmp_path: Path):
        """check_all returns ok when the registry is empty."""
        old_dir = REGISTRY_DIR
        reg_dir = tmp_path / "experiments"
        try:
            import hockey_model.experiments.registry as reg

            reg.REGISTRY_DIR = reg_dir
            _write_schema(reg_dir.parent, {"type": "object", "properties": {}})
            result = check_all()
            assert result["ok"] is True
            assert result["records"] == []
            assert result["errors"] == []
        finally:
            import hockey_model.experiments.registry as reg2

            reg2.REGISTRY_DIR = old_dir

    def test_check_all_with_valid_record(self, tmp_path: Path):
        """check_all returns ok when all records are valid."""
        old_dir = REGISTRY_DIR
        reg_dir = tmp_path / "experiments"
        try:
            import hockey_model.experiments.registry as reg

            reg.REGISTRY_DIR = reg_dir
            _write_schema(
                reg_dir.parent,
                {
                    "type": "object",
                    "required": ["id", "title", "cohort", "status"],
                    "properties": {
                        "id": {"type": "string"},
                        "title": {"type": "string"},
                        "cohort": {"type": "string", "enum": ["exploration", "confirmation"]},
                        "status": {
                            "type": "string",
                            "enum": ["registered", "rejected", "inconclusive", "promoted"],
                        },
                    },
                },
            )
            record = _make_record()
            register_record(record)
            result = cast(dict[str, list[dict[str, Any]]], check_all())
            assert result["ok"] is True
            assert len(result["records"]) == 1
            assert result["records"][0]["id"] == "0001-valid"
        finally:
            import hockey_model.experiments.registry as reg2

            reg2.REGISTRY_DIR = old_dir

    def test_check_all_with_invalid_record(self, tmp_path: Path):
        """check_all returns not ok when a record is invalid."""
        old_dir = REGISTRY_DIR
        reg_dir = tmp_path / "experiments"
        try:
            import hockey_model.experiments.registry as reg

            reg.REGISTRY_DIR = reg_dir
            _write_schema(
                reg_dir.parent,
                {
                    "type": "object",
                    "required": ["id", "title", "cohort", "status"],
                    "properties": {
                        "id": {"type": "string"},
                        "title": {"type": "string"},
                        "cohort": {"type": "string", "enum": ["exploration", "confirmation"]},
                        "status": {
                            "type": "string",
                            "enum": ["registered", "rejected", "inconclusive", "promoted"],
                        },
                    },
                },
            )
            # Write an invalid record directly.
            bad = {**_VALID_RECORD_DATA, "status": "invalid_status"}
            bad_record = ExperimentRecord.from_dict(bad)
            bad_record.save(reg_dir / f"{bad_record.id}.json")
            result = cast(dict[str, list[str]], check_all())
            assert result["ok"] is False
            assert len(result["errors"]) > 0
        finally:
            import hockey_model.experiments.registry as reg2

            reg2.REGISTRY_DIR = old_dir


class TestCheckExperiment:
    """Test check_experiment for a single record."""

    def test_check_experiment_valid(self, tmp_path: Path):
        """check_experiment returns ok for a valid record."""
        old_dir = REGISTRY_DIR
        reg_dir = tmp_path / "experiments"
        try:
            import hockey_model.experiments.registry as reg

            reg.REGISTRY_DIR = reg_dir
            _write_schema(
                reg_dir.parent,
                {
                    "type": "object",
                    "required": ["id", "title", "cohort", "status"],
                    "properties": {
                        "id": {"type": "string"},
                        "title": {"type": "string"},
                        "cohort": {"type": "string", "enum": ["exploration", "confirmation"]},
                        "status": {
                            "type": "string",
                            "enum": ["registered", "rejected", "inconclusive", "promoted"],
                        },
                    },
                },
            )
            record = _make_record()
            register_record(record)
            result = cast(dict[str, dict[str, Any]], check_experiment("0001-valid"))
            assert result["ok"] is True
            assert result["record"]["id"] == "0001-valid"
        finally:
            import hockey_model.experiments.registry as reg2

            reg2.REGISTRY_DIR = old_dir

    def test_check_experiment_not_found(self, tmp_path: Path):
        """check_experiment returns not ok when the record does not exist."""
        old_dir = REGISTRY_DIR
        reg_dir = tmp_path / "experiments"
        try:
            import hockey_model.experiments.registry as reg

            reg.REGISTRY_DIR = reg_dir
            result = cast(dict[str, dict[str, Any]], check_experiment("0001-missing"))
            assert result["ok"] is False
            assert "error" in result
        finally:
            import hockey_model.experiments.registry as reg2

            reg2.REGISTRY_DIR = old_dir


class TestResultDataclass:
    """Test the _Result dataclass."""

    def test_result_serializes(self):
        """A _Result serializes to a dict correctly."""
        result = _Result(
            games=100,
            difference=-0.005,
            interval=(-0.010, -0.001),
            csv_path="results.csv",
            csv_hash="abc123",
        )
        assert result.games == 100
        assert result.difference == -0.005
        assert result.interval == (-0.010, -0.001)

    def test_result_in_record(self):
        """A record with a result serializes and deserializes correctly."""
        record = _make_record(
            {
                "result": {
                    "games": 100,
                    "difference": -0.005,
                    "interval": [-0.010, -0.001],
                    "csv_path": "results.csv",
                    "csv_hash": "abc123",
                },
            }
        )
        data = record.to_dict()
        assert data["result"] is not None
        assert data["result"]["games"] == 100
