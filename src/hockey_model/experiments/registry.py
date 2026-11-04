"""Experiment registry: list, load, and write records.

Records live at ``experiments/NNNN-<slug>.json`` in the repository.
A checker validates them against a schema and enforces immutability.
"""

from __future__ import annotations

from pathlib import Path

from hockey_model.experiments.models import (
    ExperimentRecord,
    load_record,
    validate_against_schema,
)
from hockey_model.types import HockeyModelError

REGISTRY_DIR = Path("experiments")
SCHEMA_PATH = REGISTRY_DIR / "schema.json"


def list_records() -> list[str]:
    """Return all record IDs in the registry, sorted."""
    if not REGISTRY_DIR.exists():
        return []
    ids: list[str] = []
    for path in sorted(REGISTRY_DIR.iterdir()):
        if path.suffix == ".json" and path.name != "schema.json":
            ids.append(path.stem)
    return sorted(ids)


def get_record(record_id: str) -> ExperimentRecord:
    """Load a record by ID. Raises when not found."""
    try:
        return load_record(record_id)
    except FileNotFoundError:
        raise HockeyModelError(f"experiment {record_id!r} not found") from None


def register_record(record: ExperimentRecord) -> None:
    """Write a new record to the registry.

    Raises when a record with the same ID already exists.
    """
    path = REGISTRY_DIR / f"{record.id}.json"
    if path.exists():
        raise HockeyModelError(
            f"experiment {record.id!r} already exists; a change requires a new record, not an edit"
        )
    validate_against_schema(record, SCHEMA_PATH)
    record.save(path)


def find_record_by_id(record_id: str) -> ExperimentRecord | None:
    """Load a record by ID, or return None when not found."""
    try:
        return load_record(record_id)
    except FileNotFoundError:
        return None
