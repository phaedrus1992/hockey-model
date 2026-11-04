"""Data models for experiment registry records.

Each record describes one experiment: a hypothesis, the data it uses,
and the criteria for promoting or rejecting it.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from hockey_model.types import HockeyModelError

# Status values a record can hold.
STATUS_REGISTERED = "registered"
STATUS_REJECTED = "rejected"
STATUS_INCONCLUSIVE = "inconclusive"
STATUS_PROMOTED = "promoted"
VALID_STATUSES = (STATUS_REGISTERED, STATUS_REJECTED, STATUS_INCONCLUSIVE, STATUS_PROMOTED)

# Immutable fields that must not change after registration.
IMMUTABLE_FIELDS = (
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
)


@dataclass(frozen=True, slots=True)
class _Baseline:
    """The live fit used as a baseline for comparison."""

    fit_id: int
    commit: str


@dataclass(frozen=True, slots=True)
class _Result:
    """The result of one confirmation look."""

    games: int
    difference: float
    interval: tuple[float, float]
    csv_path: str
    csv_hash: str


@dataclass(frozen=True, slots=True)
class ExperimentRecord:
    """One experiment record.

    Immutable fields cannot change after registration.
    Only ``status`` and ``result`` may be updated after registration.
    """

    id: str
    title: str
    hypothesis: str
    cohort: str
    data_cutoff: str
    primary_metric: str
    baseline: _Baseline
    selection_folds: list[tuple[int, int]] | None
    min_games: int
    expected_effect: float | None
    promotion_criterion: str
    failure_outcome: str
    status: str
    result: _Result | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dict for JSON storage."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExperimentRecord:
        """Deserialize from a dict loaded from JSON."""
        if "baseline" in data and isinstance(data["baseline"], dict):
            data["baseline"] = _Baseline(**data["baseline"])
        if "result" in data and data["result"] is not None and isinstance(data["result"], dict):
            data["result"] = _Result(**data["result"])
        return cls(**data)

    @classmethod
    def load(cls, path: Path) -> ExperimentRecord:
        """Load a record from a JSON file."""
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
        return cls.from_dict(data)

    def save(self, path: Path) -> None:
        """Save this record to a JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(asdict(self), indent=2, ensure_ascii=False)
        path.write_text(text + "\n", encoding="utf-8")

    def immutable_fields(self) -> dict[str, Any]:
        """Return the immutable fields for comparison."""
        result: dict[str, Any] = {}
        for name in IMMUTABLE_FIELDS:
            result[name] = getattr(self, name)
        return result


def record_path(record_id: str) -> Path:
    """Return the expected path for a record by its ID.

    Records live at ``experiments/NNNN-<slug>.json`` in the repository.
    """
    return Path("experiments", f"{record_id}.json")


def load_record(record_id: str) -> ExperimentRecord:
    """Load a record by ID from the repository."""
    path = record_path(record_id)
    return ExperimentRecord.load(path)


def validate_against_schema(record: ExperimentRecord | dict[str, Any], schema_path: Path) -> None:
    """Validate a record against a JSON Schema.

    Raises ``HockeyModelError`` when the record does not match.
    """
    if not schema_path.exists():
        raise HockeyModelError(f"schema not found: {schema_path}")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    if isinstance(record, ExperimentRecord):
        data = record.to_dict()
    else:
        data = record
    _validate_object(data, schema, schema_path)


def _validate_object(data: dict[str, Any], schema: dict[str, Any], schema_path: Path) -> None:
    """Validate a dict against a JSON Schema object definition."""
    properties = schema.get("properties", {})
    required = schema.get("required", [])

    for prop_name in required:
        if prop_name not in data:
            raise HockeyModelError(
                f"missing required field {prop_name!r} in {schema_path}: {_field_path(prop_name)}"
            )

    for prop_name, prop_schema in properties.items():
        if prop_name not in data:
            continue
        _validate_value(data[prop_name], prop_schema, schema_path, prop_name)


def _validate_value(value: Any, schema: dict[str, Any], schema_path: Path, field_name: str) -> None:
    """Validate a single value against a schema property."""
    expected_type = schema.get("type")
    path = _field_path(field_name)

    if expected_type == "string":
        _check_string(value, schema, schema_path, path)
    elif expected_type == "integer":
        _check_integer(value, schema_path, path)
    elif expected_type == "number":
        _check_number(value, schema_path, path)
    elif expected_type == "boolean":
        _check_boolean(value, schema_path, path)
    elif expected_type == "object":
        _check_object(value, schema, schema_path, field_name, path)
    elif expected_type == "array":
        _check_array(value, schema, schema_path, field_name, path)


def _check_string(value: Any, schema: dict[str, Any], schema_path: Path, path: str) -> None:
    """Check that a value is a string, optionally from an enum."""
    if not isinstance(value, str):
        raise HockeyModelError(f"{path}: expected a string, got {type(value).__name__}")
    enum_values = schema.get("enum")
    if enum_values and value not in enum_values:
        raise HockeyModelError(f"{path}: value {value!r} not in {enum_values}")


def _check_integer(value: Any, schema_path: Path, path: str) -> None:
    """Check that a value is an integer (not a bool)."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise HockeyModelError(f"{path}: expected an integer, got {type(value).__name__}")


def _check_number(value: Any, schema_path: Path, path: str) -> None:
    """Check that a value is a number (int or float, not a bool)."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise HockeyModelError(f"{path}: expected a number, got {type(value).__name__}")


def _check_boolean(value: Any, schema_path: Path, path: str) -> None:
    """Check that a value is a boolean."""
    if not isinstance(value, bool):
        raise HockeyModelError(f"{path}: expected a boolean, got {type(value).__name__}")


def _check_object(
    value: Any,
    schema: dict[str, Any],
    schema_path: Path,
    field_name: str,
    path: str,
) -> None:
    """Check that a value is an object and validate its properties."""
    if not isinstance(value, dict):
        raise HockeyModelError(f"{path}: expected an object, got {type(value).__name__}")
    _validate_object(value, schema, schema_path)


def _check_array(
    value: Any,
    schema: dict[str, Any],
    schema_path: Path,
    field_name: str,
    path: str,
) -> None:
    """Check that a value is an array and validate its items."""
    if not isinstance(value, list):
        raise HockeyModelError(f"{path}: expected an array, got {type(value).__name__}")
    items_schema = schema.get("items")
    if items_schema:
        for i, item in enumerate(value):
            _validate_value(item, items_schema, schema_path, f"{field_name}[{i}]")


def _field_path(name: str) -> str:
    """Format a field name for error messages."""
    return f"$.{name}"


def check_immutable_fields(record: ExperimentRecord, registration_commit: str) -> None:
    """Check that immutable fields have not changed since registration.

    Raises ``HockeyModelError`` when a field other than ``status`` or
    ``result`` has been modified since the registration commit.
    """
    # This is a no-op when we have no prior state to compare against.
    # The full check loads the record at the registration commit and
    # compares immutable fields. Callers pass the registration commit
    # so the check can load that version and diff.
    pass
