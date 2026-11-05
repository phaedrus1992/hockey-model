"""Experiment registry: list, load, and write records.

Records live at ``experiments/NNNN-<slug>.json`` in the repository.
A checker validates them against a schema and enforces immutability.
"""

from __future__ import annotations

import re
from pathlib import Path

from hockey_model.experiments.models import (
    ExperimentRecord,
    validate_against_schema,
)
from hockey_model.types import HockeyModelError

REGISTRY_DIR = Path("experiments")
SCHEMA_PATH = REGISTRY_DIR / "schema.json"
CHECK_OUTPUT_SCHEMA_PATH = REGISTRY_DIR / "check_output.schema.json"
# Per-game CSVs of a confirmation run live here so the record's hash points at a
# file other people can read.
RESULTS_DIR = REGISTRY_DIR / "results"

# A record id is a four-digit number and a slug. The number is the record's slot
# in the registry, so two records cannot share it.
_RECORD_ID = re.compile(r"^[0-9]{4}-[a-z0-9][a-z0-9-]*$")


def list_records() -> list[str]:
    """Return all record IDs in the registry, sorted."""
    if not REGISTRY_DIR.exists():
        return []
    ids: list[str] = []
    for path in sorted(REGISTRY_DIR.iterdir()):
        if path.suffix == ".json" and _RECORD_ID.fullmatch(path.stem):
            ids.append(path.stem)
    return sorted(ids)


def get_record(record_id: str) -> ExperimentRecord:
    """Load a record by ID. Raises when the record is not in the registry."""
    if not record_exists(record_id):
        raise HockeyModelError(f"experiment {record_id!r} not found")
    return ExperimentRecord.load(REGISTRY_DIR / f"{record_id}.json")


def record_exists(record_id: str) -> bool:
    """Return True when a record file for the ID is in the registry."""
    return (REGISTRY_DIR / f"{record_id}.json").exists()


def register_record(record: ExperimentRecord) -> None:
    """Write a new record to the registry.

    Raises when a record with the same ID, or the same registry number, already
    exists.
    """
    if not _RECORD_ID.fullmatch(record.id):
        raise HockeyModelError(
            f"invalid experiment id {record.id!r}: use NNNN-slug, for example 0002-attempt-form"
        )
    path = REGISTRY_DIR / f"{record.id}.json"
    if path.exists():
        raise HockeyModelError(
            f"experiment {record.id!r} already exists; a change requires a new record, not an edit"
        )
    number = record.id.split("-", 1)[0]
    taken = {other.split("-", 1)[0] for other in list_records()}
    if number in taken:
        raise HockeyModelError(
            f"experiment number {number} is taken; a new record needs a new number"
        )
    validate_against_schema(record, SCHEMA_PATH)
    record.save(path)


def find_record_by_id(record_id: str) -> ExperimentRecord | None:
    """Load a record by ID, or return None when it is not in the registry."""
    if not record_exists(record_id):
        return None
    try:
        return ExperimentRecord.load(REGISTRY_DIR / f"{record_id}.json")
    except HockeyModelError as exc:
        raise HockeyModelError(f"experiment {record_id!r}: {exc}") from exc
