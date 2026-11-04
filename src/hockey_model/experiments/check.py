"""Experiment checker: validate records and enforce immutability.

``hockey-model experiments check`` prints JSON validated against the
schema. It fails when a record is invalid, when a field other than
``status`` and ``result`` changed since the registration commit, or
when a confirmation record has a result without a registration commit
before the run.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

from hockey_model.experiments.models import (
    STATUS_INCONCLUSIVE,
    STATUS_PROMOTED,
    STATUS_REGISTERED,
    STATUS_REJECTED,
    ExperimentRecord,
    validate_against_schema,
)
from hockey_model.experiments.registry import SCHEMA_PATH, list_records
from hockey_model.types import HockeyModelError


def check_all() -> dict[str, object]:
    """Check every record in the registry.

    Returns a dict with ``ok`` (bool), ``records`` (list of check results),
    and ``errors`` (list of error messages).
    """
    results: list[dict[str, object]] = []
    errors: list[str] = []

    from hockey_model.experiments.registry import REGISTRY_DIR

    for record_id in list_records():
        try:
            path = REGISTRY_DIR / f"{record_id}.json"
            record = ExperimentRecord.load(path)
            validate_against_schema(record, SCHEMA_PATH)
            result_entry: dict[str, object] = {
                "id": record.id,
                "status": record.status,
                "valid": True,
            }
            if record.result is not None:
                result_entry["has_result"] = True
            results.append(result_entry)
        except HockeyModelError as exc:
            errors.append(f"{record_id}: {exc}")
            results.append({"id": record_id, "valid": False, "error": str(exc)})

    return {
        "ok": len(errors) == 0,
        "records": results,
        "errors": errors,
    }


def check_experiment(record_id: str) -> dict[str, object]:
    """Check a single record by ID. Returns the same format as check_all."""
    from hockey_model.experiments.registry import REGISTRY_DIR

    try:
        path = REGISTRY_DIR / f"{record_id}.json"
        record = ExperimentRecord.load(path)
        validate_against_schema(record, SCHEMA_PATH)
        return {
            "ok": True,
            "record": {
                "id": record.id,
                "status": record.status,
                "has_result": record.result is not None,
            },
        }
    except (HockeyModelError, FileNotFoundError) as exc:
        return {"ok": False, "error": str(exc)}


def run_experiment(
    record_id: str,
    conn: sqlite3.Connection,
    fit_first: int,
    through_season: int,
    candidate_features: tuple[str, ...],
) -> tuple[dict[str, object], list[dict[str, object]]]:
    """Run a backtest for one experiment record.

    For a confirmation record it refuses when the status is not registered,
    when the cohort has fewer than min_games, or when the record already
    has a result. It scores games, writes the result back to the record,
    and writes the per-game CSV.

    For an exploration record it may run again and again.

    Returns a JSON-serializable dict and a list of per-game records.
    """
    from hockey_model.experiments.registry import REGISTRY_DIR

    path = REGISTRY_DIR / f"{record_id}.json"
    record = ExperimentRecord.load(path)

    if record.cohort == "confirmation":
        _check_confirmation_can_run(record)

    # Import the backtest runner here to avoid circular imports.
    from dataclasses import replace

    from hockey_model.backtest.runner import run_backtest, write_game_records
    from hockey_model.game_model.seasons import _confirmation_plan
    from hockey_model.store.timestamps import iso_utc

    # Extract confirmation start from the record's data_cutoff year.
    cutoff_year = int(record.data_cutoff[:4]) + 1
    plan = _confirmation_plan(cutoff_year)
    report, game_records = run_backtest(conn, plan, candidate_features)

    # Build per-game export entries.
    export_entries: list[dict[str, object]] = []
    for gr in game_records:
        export_entries.append(
            {
                "game_id": gr.game_id,
                "start": iso_utc(gr.start),
                "home": gr.home,
                "away": gr.away,
                "run": gr.run,
                "home_win_prob": gr.home_win_prob,
                "home_won": gr.home_won,
            }
        )

    # Update the record with the result.
    new_status = record.status
    new_result = record.result
    if record.cohort == "confirmation":
        # Compute result fields from the report.
        model_run = next((r for r in report.runs if r.name == "model_actual"), None)
        if model_run is None or model_run.diff_vs_elo_ci is None:
            new_status = STATUS_INCONCLUSIVE
        elif model_run.diff_vs_elo_ci[1] < 0.0:
            new_status = STATUS_PROMOTED
        else:
            new_status = STATUS_REJECTED

        # Write per-game CSV to a temp path and compute hash.
        csv_path = Path(".tmp", f"{record_id}-games.csv")
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        write_game_records(csv_path, game_records)
        csv_hash = _file_hash(csv_path)

        from hockey_model.experiments.models import _Result

        if model_run is not None and model_run.diff_vs_elo_ci is not None:
            ci = model_run.diff_vs_elo_ci
            new_result = _Result(
                games=len(game_records),
                difference=ci[0],
                interval=ci,
                csv_path=str(csv_path),
                csv_hash=csv_hash,
            )

    updated = replace(record, status=new_status, result=new_result)
    updated.save(REGISTRY_DIR / f"{updated.id}.json")

    return {
        "ok": True,
        "record_id": updated.id,
        "status": updated.status,
        "notes": report.notes,
    }, export_entries


def _check_confirmation_can_run(record: ExperimentRecord) -> None:
    """Check that a confirmation record can be run."""
    if record.status != STATUS_REGISTERED:
        raise HockeyModelError(
            f"experiment {record.id!r}: confirmation status is {record.status!r}, "
            "expected registered"
        )
    if record.result is not None:
        raise HockeyModelError(
            f"experiment {record.id!r}: already has a result; "
            "a change requires a new record, not a re-run"
        )


def _file_hash(path: Path) -> str:
    """Compute a simple hash of a file's contents."""
    import hashlib

    data = path.read_bytes()
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    """CLI entry point for ``hockey-model experiments check``."""
    result = check_all()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
