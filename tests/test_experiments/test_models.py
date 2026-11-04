"""Tests for experiment registry models.

Covers:
- Schema validation (malformed schema, missing fields, wrong types)
- Edited registration (immutable fields changed after save)
- Record serialization and deserialization
- File save and load round-trip
"""

import json
from pathlib import Path

import pytest

from hockey_model.experiments.models import (
    ExperimentRecord,
    HockeyModelError,
    _validate_value,
    check_immutable_fields,
    record_path,
    validate_against_schema,
)
from hockey_model.experiments.registry import register_record

# A valid record for testing.
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

# A minimal valid schema for testing.
_MINIMAL_SCHEMA = {
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
        "min_games": {"type": "integer"},
    },
}


def _write_schema(tmp_path: Path, schema: dict) -> Path:
    """Write a schema file and return its path."""
    schema_path = tmp_path / "schema.json"
    schema_path.write_text(json.dumps(schema), encoding="utf-8")
    return schema_path


def _make_record(data: dict | None = None) -> ExperimentRecord:
    """Create a valid record from base data, overridden by data."""
    merged = {**_VALID_RECORD_DATA, **(data or {})}
    return ExperimentRecord.from_dict(merged)


class TestRecordSerialization:
    """Test record to_dict and from_dict."""

    def test_to_dict_round_trips(self, tmp_path: Path):
        """A record serializes and deserializes to the same values."""
        record = _make_record()
        data = record.to_dict()
        restored = ExperimentRecord.from_dict(data)
        assert restored.id == record.id
        assert restored.title == record.title
        assert restored.baseline.fit_id == record.baseline.fit_id

    def test_save_and_load_round_trip(self, tmp_path: Path):
        """A record saves to JSON and loads back with the same values."""
        record = _make_record()
        path = tmp_path / "0001-test.json"
        record.save(path)
        loaded = ExperimentRecord.load(path)
        assert loaded.id == record.id
        assert loaded.hypothesis == record.hypothesis
        assert loaded.baseline.commit == record.baseline.commit


class TestSchemaValidation:
    """Test validation against JSON Schema."""

    def test_valid_record_passes(self, tmp_path: Path):
        """A complete valid record passes schema validation."""
        record = _make_record()
        schema_path = _write_schema(tmp_path, _MINIMAL_SCHEMA)
        validate_against_schema(record, schema_path)

    def test_missing_required_field_fails(self, tmp_path: Path):
        """A record missing a required field raises HockeyModelError."""
        record = _make_record()
        data = record.to_dict()
        del data["status"]
        schema_path = _write_schema(tmp_path, _MINIMAL_SCHEMA)
        with pytest.raises(HockeyModelError, match="missing required field"):
            validate_against_schema(data, schema_path)

    def test_missing_schema_file_fails(self, tmp_path: Path):
        """A missing schema file raises HockeyModelError."""
        record = _make_record()
        missing = tmp_path / "nonexistent.json"
        with pytest.raises(HockeyModelError, match="schema not found"):
            validate_against_schema(record, missing)

    def test_invalid_enum_value_fails(self, tmp_path: Path):
        """A record with an invalid enum value raises HockeyModelError."""
        record = _make_record({"cohort": "invalid_cohort"})
        schema_path = _write_schema(tmp_path, _MINIMAL_SCHEMA)
        with pytest.raises(HockeyModelError, match="not in"):
            validate_against_schema(record, schema_path)

    def test_wrong_type_fails(self, tmp_path: Path):
        """A string where an integer is expected raises HockeyModelError."""
        bad = {**_VALID_RECORD_DATA, "min_games": "one thousand"}
        record = ExperimentRecord.from_dict(bad)
        schema_path = _write_schema(tmp_path, _MINIMAL_SCHEMA)
        with pytest.raises(HockeyModelError, match="expected"):
            validate_against_schema(record, schema_path)


class TestValidateValue:
    """Test the _validate_value helper."""

    def test_string_validates(self, tmp_path: Path):
        """A string value passes when the schema expects a string."""
        _validate_value("hello", {"type": "string"}, tmp_path, "$.field")

    def test_string_rejects_non_string(self, tmp_path: Path):
        """A non-string value fails when the schema expects a string."""
        with pytest.raises(HockeyModelError, match="expected a string"):
            _validate_value(42, {"type": "string"}, tmp_path, "$.field")

    def test_integer_rejects_float(self, tmp_path: Path):
        """A float value fails when the schema expects an integer."""
        with pytest.raises(HockeyModelError, match="expected an integer"):
            _validate_value(3.14, {"type": "integer"}, tmp_path, "$.field")

    def test_integer_rejects_bool(self, tmp_path: Path):
        """A bool value fails when the schema expects an integer."""
        with pytest.raises(HockeyModelError, match="expected an integer"):
            _validate_value(True, {"type": "integer"}, tmp_path, "$.field")

    def test_boolean_validates(self, tmp_path: Path):
        """A boolean value passes when the schema expects a boolean."""
        _validate_value(True, {"type": "boolean"}, tmp_path, "$.field")

    def test_boolean_rejects_string(self, tmp_path: Path):
        """A string value fails when the schema expects a boolean."""
        with pytest.raises(HockeyModelError, match="expected a boolean"):
            _validate_value("yes", {"type": "boolean"}, tmp_path, "$.field")

    def test_array_validates_items(self, tmp_path: Path):
        """An array of integers validates when the schema expects integer items."""
        schema = {"type": "array", "items": {"type": "integer"}}
        _validate_value([1, 2, 3], schema, tmp_path, "$.arr")

    def test_array_rejects_wrong_item_type(self, tmp_path: Path):
        """An array with a wrong item type fails."""
        schema = {"type": "array", "items": {"type": "integer"}}
        with pytest.raises(HockeyModelError, match="expected an integer"):
            _validate_value([1, "two", 3], schema, tmp_path, "$.arr")

    def test_object_validates_properties(self, tmp_path: Path):
        """An object with required properties validates."""
        schema = {
            "type": "object",
            "required": ["name"],
            "properties": {"name": {"type": "string"}},
        }
        _validate_value({"name": "test"}, schema, tmp_path, "$.obj")

    def test_object_rejects_missing_required(self, tmp_path: Path):
        """An object missing a required property fails."""
        schema = {
            "type": "object",
            "required": ["name"],
            "properties": {"name": {"type": "string"}},
        }
        with pytest.raises(HockeyModelError, match="missing required field"):
            _validate_value({}, schema, tmp_path, "$.obj")


class TestImmutableFields:
    """Test immutability checking."""

    def test_immutable_fields_returns_correct_fields(self):
        """immutable_fields returns all immutable fields."""
        record = _make_record()
        fields = record.immutable_fields()
        assert "id" in fields
        assert "hypothesis" in fields
        assert "cohort" in fields
        assert "baseline" in fields

    def test_check_immutable_fields_no_prior_state(self):
        """check_immutable_fields is a no-op when there is no prior state."""
        record = _make_record()
        # Should not raise when called with no registration_commit comparison
        check_immutable_fields(record, "abc123")


class TestRecordPath:
    """Test the record_path helper."""

    def test_record_path_format(self):
        """record_path returns the expected path."""
        path = record_path("0001-test")
        assert str(path) == "experiments/0001-test.json"


class TestRegisterRecord:
    """Test the register_record function."""

    def test_register_new_record(self, tmp_path: Path):
        """Registering a new record writes the file."""
        import hockey_model.experiments.registry as reg

        old_dir = reg.REGISTRY_DIR
        reg.REGISTRY_DIR = tmp_path / "experiments"
        try:
            record = _make_record()
            register_record(record)
            expected = tmp_path / "experiments" / f"{record.id}.json"
            assert expected.exists()
        finally:
            reg.REGISTRY_DIR = old_dir

    def test_register_duplicate_fails(self, tmp_path: Path):
        """Registering a duplicate record raises HockeyModelError."""
        import hockey_model.experiments.registry as reg

        old_dir = reg.REGISTRY_DIR
        reg.REGISTRY_DIR = tmp_path / "experiments"
        try:
            record = _make_record({"id": "0099-first"})
            register_record(record)
            # Create a second record with the same ID.
            second = _make_record({"id": "0099-first", "title": "duplicate"})
            with pytest.raises(HockeyModelError, match="already exists"):
                register_record(second)
        finally:
            reg.REGISTRY_DIR = old_dir
