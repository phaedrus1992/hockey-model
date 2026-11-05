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
from hockey_model.experiments.schemas import EXPERIMENT_SCHEMA
from hockey_model.types import HockeyModelError

# The registry is repository data, not package data, so every call names the
# repository root it reads from. The schema ships with the package, so validation
# does not depend on the working directory.
REGISTRY_DIR_NAME = "experiments"
# Per-game CSVs of a confirmation run live here so the record's hash points at a
# file other people can read.
RESULTS_DIR_NAME = "results"

# A record id is a four-digit number and a slug. The number is the record's slot
# in the registry, so two records cannot share it.
_RECORD_ID = re.compile(r"^[0-9]{4}-[a-z0-9][a-z0-9-]*$")


def registry_dir(repo_root: Path) -> Path:
    """Return the registry directory inside the repository root."""
    return repo_root / REGISTRY_DIR_NAME


def results_dir(repo_root: Path) -> Path:
    """Return the directory that holds the per-game CSVs of a confirmation run."""
    return registry_dir(repo_root) / RESULTS_DIR_NAME


def list_records(repo_root: Path) -> list[str]:
    """Return all record IDs in the registry, sorted."""
    registry = registry_dir(repo_root)
    if not registry.exists():
        return []
    ids: list[str] = []
    for path in sorted(registry.iterdir()):
        if path.suffix == ".json" and _RECORD_ID.fullmatch(path.stem):
            ids.append(path.stem)
    return sorted(ids)


def get_record(record_id: str, repo_root: Path) -> ExperimentRecord:
    """Load a record by ID. Raises when the record is not in the registry."""
    if not record_exists(record_id, repo_root):
        raise HockeyModelError(f"experiment {record_id!r} not found")
    return ExperimentRecord.load(registry_dir(repo_root) / f"{record_id}.json")


def record_exists(record_id: str, repo_root: Path) -> bool:
    """Return True when a record file for the ID is in the registry."""
    return (registry_dir(repo_root) / f"{record_id}.json").exists()


def register_record(record: ExperimentRecord, repo_root: Path) -> None:
    """Write a new record to the registry.

    Raises when a record with the same ID, or the same registry number, already
    exists.
    """
    if not _RECORD_ID.fullmatch(record.id):
        raise HockeyModelError(
            f"invalid experiment id {record.id!r}: use NNNN-slug, for example 0002-attempt-form"
        )
    path = registry_dir(repo_root) / f"{record.id}.json"
    if path.exists():
        raise HockeyModelError(
            f"experiment {record.id!r} already exists; a change requires a new record, not an edit"
        )
    number = record.id.split("-", 1)[0]
    taken = {other.split("-", 1)[0] for other in list_records(repo_root)}
    if number in taken:
        raise HockeyModelError(
            f"experiment number {number} is taken; a new record needs a new number"
        )
    validate_against_schema(record, EXPERIMENT_SCHEMA)
    record.save(path)


def find_record_by_id(record_id: str, repo_root: Path) -> ExperimentRecord | None:
    """Load a record by ID, or return None when it is not in the registry."""
    if not record_exists(record_id, repo_root):
        return None
    try:
        return ExperimentRecord.load(registry_dir(repo_root) / f"{record_id}.json")
    except HockeyModelError as exc:
        raise HockeyModelError(f"experiment {record_id!r}: {exc}") from exc
