"""Tests for experiment registry models.

Covers:
- Schema validation (types, unions, patterns, bounds, formats, unknown keywords)
- Record serialization and deserialization
- File save and load round-trip
"""

from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from hockey_model.experiments.models import (
    ExperimentRecord,
    HockeyModelError,
    record_from_text,
    validate_against_schema,
)
from hockey_model.experiments.schemas import EXPERIMENT_SCHEMA

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
    "candidate_features": ["xg_form"],
    "look_number": 1,
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


def _make_record(data: dict | None = None) -> ExperimentRecord:
    """Create a valid record from base data, overridden by data."""
    merged = {**_VALID_RECORD_DATA, **(data or {})}
    return ExperimentRecord.from_dict(merged)


class TestRecordSerialization:
    """Test record to_dict and from_dict."""

    def test_to_dict_round_trips(self):
        """A record serializes and deserializes to the same values."""
        record = _make_record()
        restored = ExperimentRecord.from_dict(record.to_dict())
        assert restored == record

    def test_json_round_trip_keeps_values(self, tmp_path: Path):
        """A record saved to JSON loads back with the same values."""
        record = _make_record()
        path = tmp_path / "0001-test.json"
        record.save(path)
        loaded = ExperimentRecord.load(path)
        assert loaded.id == record.id
        assert loaded.hypothesis == record.hypothesis
        assert loaded.baseline.commit == record.baseline.commit
        assert loaded.candidate_features == ("xg_form",)

    def test_from_dict_rejects_an_unknown_key(self):
        """An extra key raises HockeyModelError, not a bare TypeError."""
        bad = {**_VALID_RECORD_DATA, "promoted": True}
        with pytest.raises(HockeyModelError, match="cannot build a record"):
            ExperimentRecord.from_dict(bad)

    def test_result_interval_survives_json(self, tmp_path: Path):
        """A result interval keeps its two bounds through JSON."""
        record = _make_record(
            {
                "result": {
                    "games": 100,
                    "difference": -0.005,
                    "interval": [-0.010, -0.001],
                    "csv_path": "experiments/results/0001-test-games.csv",
                    "csv_hash": "0" * 64,
                }
            }
        )
        path = tmp_path / "0001-test.json"
        record.save(path)
        loaded = ExperimentRecord.load(path)
        assert loaded.result is not None
        assert loaded.result.games == 100
        assert list(loaded.result.interval) == [-0.010, -0.001]

    def test_immutable_fields_lists_every_immutable_name(self):
        """immutable_fields returns every field that may not change after registration."""
        fields = _make_record().immutable_fields()
        assert set(fields) == {
            "id",
            "title",
            "hypothesis",
            "cohort",
            "data_cutoff",
            "primary_metric",
            "baseline",
            "selection_folds",
            "min_games",
            "expected_effect",
            "promotion_criterion",
            "failure_outcome",
            "candidate_features",
            "look_number",
        }

    def test_record_from_text_rejects_a_non_object(self):
        """A JSON array is not a record."""
        with pytest.raises(HockeyModelError, match="must be a JSON object"):
            record_from_text("[1, 2]", "test input")

    def test_record_from_text_rejects_bad_json(self):
        """Broken JSON names the source of the text."""
        with pytest.raises(HockeyModelError, match="invalid JSON in test input"):
            record_from_text("{", "test input")


class TestSchemaValidation:
    """Test validation against a JSON Schema."""

    def test_valid_record_passes(self, tmp_path: Path):
        """A complete valid record passes schema validation."""
        validate_against_schema(_make_record(), _MINIMAL_SCHEMA)

    def test_missing_required_field_fails(self, tmp_path: Path):
        """A record missing a required field raises HockeyModelError."""
        data = _make_record().to_dict()
        del data["status"]
        with pytest.raises(HockeyModelError, match="missing required field"):
            validate_against_schema(data, _MINIMAL_SCHEMA)

    def test_invalid_enum_value_fails(self, tmp_path: Path):
        """A record with an invalid enum value raises HockeyModelError."""
        record = _make_record({"cohort": "invalid_cohort"})
        with pytest.raises(HockeyModelError, match="not in"):
            validate_against_schema(record, _MINIMAL_SCHEMA)

    def test_wrong_type_fails(self, tmp_path: Path):
        """A string where an integer is expected raises HockeyModelError."""
        bad = {**_VALID_RECORD_DATA, "min_games": "one thousand"}
        with pytest.raises(HockeyModelError, match="expected an integer"):
            validate_against_schema(bad, _MINIMAL_SCHEMA)

    def test_union_type_accepts_null(self, tmp_path: Path):
        """A field declared as object or null accepts null."""
        schema = {"type": "object", "properties": {"result": {"type": ["object", "null"]}}}
        validate_against_schema({"result": None}, schema)

    def test_union_type_rejects_a_string(self, tmp_path: Path):
        """A field declared as object or null rejects a string."""
        schema = {"type": "object", "properties": {"result": {"type": ["object", "null"]}}}
        with pytest.raises(HockeyModelError, match="expected an object or null, got str"):
            validate_against_schema({"result": "promoted, trust me"}, schema)

    def test_union_type_checks_object_properties(self, tmp_path: Path):
        """A union type still validates the properties of an object value."""
        schema = {
            "type": "object",
            "properties": {
                "result": {
                    "type": ["object", "null"],
                    "properties": {"games": {"type": "integer"}},
                }
            },
        }
        with pytest.raises(HockeyModelError, match=r"\$\.result\.games: expected an integer"):
            validate_against_schema({"result": {"games": "lots"}}, schema)

    def test_pattern_is_enforced(self, tmp_path: Path):
        """A string that does not match the pattern fails."""
        schema = {
            "type": "object",
            "properties": {"id": {"type": "string", "pattern": "^[0-9]{4}-.*$"}},
        }
        with pytest.raises(HockeyModelError, match="does not match pattern"):
            validate_against_schema({"id": "xyz"}, schema)

    def test_array_bounds_are_enforced(self, tmp_path: Path):
        """minItems and maxItems fail a fold with the wrong length."""
        schema = {
            "type": "object",
            "properties": {
                "selection_folds": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "minItems": 2,
                        "maxItems": 2,
                    },
                }
            },
        }
        with pytest.raises(HockeyModelError, match="expected at most 2 items"):
            validate_against_schema({"selection_folds": [[1, 2, 3]]}, schema)
        with pytest.raises(HockeyModelError, match="expected at least 2 items"):
            validate_against_schema({"selection_folds": [[1]]}, schema)

    def test_date_format_is_enforced(self, tmp_path: Path):
        """A data_cutoff that is not a date fails."""
        schema = {
            "type": "object",
            "properties": {"data_cutoff": {"type": "string", "format": "date"}},
        }
        with pytest.raises(HockeyModelError, match="is not a YYYY-MM-DD date"):
            validate_against_schema({"data_cutoff": "whenever"}, schema)

    def test_numeric_minimum_is_enforced(self, tmp_path: Path):
        """A min_games of zero fails a minimum of one."""
        schema = {"type": "object", "properties": {"min_games": {"type": "integer", "minimum": 1}}}
        with pytest.raises(HockeyModelError, match="below the minimum"):
            validate_against_schema({"min_games": 0}, schema)

    def test_unknown_keyword_raises(self, tmp_path: Path):
        """A schema keyword the validator does not implement fails instead of passing quietly."""
        schema = {"type": "object", "properties": {"id": {"type": "string", "const": "0001-test"}}}
        with pytest.raises(HockeyModelError, match="does not implement the schema keyword"):
            validate_against_schema({"id": "anything"}, schema)

    def test_nested_paths_are_named(self, tmp_path: Path):
        """An error names the full path of the failing field."""
        schema = {
            "type": "object",
            "properties": {
                "baseline": {"type": "object", "properties": {"fit_id": {"type": "integer"}}}
            },
        }
        with pytest.raises(HockeyModelError, match=r"\$\.baseline\.fit_id"):
            validate_against_schema({"baseline": {"fit_id": 1.5}}, schema)


class TestSchemaRoundTrip:
    """Property test: every record built from valid parts validates against the real schema."""

    @given(
        number=st.integers(min_value=1, max_value=9999),
        slug=st.from_regex(r"[a-z][a-z0-9-]{0,20}", fullmatch=True),
        min_games=st.integers(min_value=1, max_value=100000),
        looks=st.integers(min_value=1, max_value=50),
    )
    def test_a_well_formed_record_passes_the_registry_schema(self, number, slug, min_games, looks):
        """Any record with valid parts passes the registry schema."""
        record = _make_record(
            {
                "id": f"{number:04d}-{slug}",
                "min_games": min_games,
                "look_number": looks,
                "selection_folds": None,
            }
        )
        validate_against_schema(record, EXPERIMENT_SCHEMA)
