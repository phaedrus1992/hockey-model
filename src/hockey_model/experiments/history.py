"""Git-history checks for experiment records.

Two registry rules are enforced against commits, not against the file alone:
a record is frozen at registration, and a confirmation run is one-shot.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from hockey_model.experiments.models import (
    IMMUTABLE_FIELDS,
    ExperimentRecord,
    record_from_text,
)
from hockey_model.experiments.registry import REGISTRY_DIR_NAME
from hockey_model.types import HockeyModelError


def record_relative_path(record_id: str) -> str:
    """Return the path of a record inside the repository, as git sees it."""
    return f"{REGISTRY_DIR_NAME}/{record_id}.json"


def registration_commit(record_id: str, repo_root: Path) -> str | None:
    """Return the commit that first added the record, or None when git does not track it."""
    if not _is_work_tree(repo_root):
        return None
    commits = _git(
        ["log", "--format=%H", "--", record_relative_path(record_id)],
        repo_root,
    ).split()
    return commits[-1] if commits else None


def check_immutable_fields(
    record: ExperimentRecord,
    registration_commit_sha: str,
    repo_root: Path,
) -> None:
    """Raise when a field that the record carried at registration changed after it.

    A field the record did not carry at registration is a schema addition, not a
    broken promise, so it is not compared.
    """
    relative = record_relative_path(record.id)
    text = _git(["show", f"{registration_commit_sha}:{relative}"], repo_root)
    prior = record_from_text(text, f"commit {registration_commit_sha} of {relative}")
    registered = json.loads(text)
    current = record.to_dict()
    before = prior.to_dict()
    changed = [
        name for name in IMMUTABLE_FIELDS if name in registered and current[name] != before[name]
    ]
    if changed:
        raise HockeyModelError(
            f"experiment {record.id!r}: immutable field(s) {', '.join(changed)} changed "
            f"after registration commit {registration_commit_sha}"
        )


def check_one_shot(record: ExperimentRecord, repo_root: Path) -> None:
    """Raise when the record's history holds a result that HEAD no longer carries.

    A confirmation run is one-shot. Deleting or replacing a committed result is a
    new experiment, so it needs a new record.
    """
    relative = record_relative_path(record.id)
    current = record.to_dict().get("result")
    for commit in _git(["log", "--format=%H", "--", relative], repo_root).split():
        prior = json.loads(_git(["show", f"{commit}:{relative}"], repo_root)).get("result")
        if prior is None:
            continue
        if prior != current:
            raise HockeyModelError(
                f"experiment {record.id!r}: commit {commit} recorded a result that the "
                "record no longer holds; a confirmation run is one-shot, so a new run "
                "needs a new record"
            )


def _is_work_tree(repo_root: Path) -> bool:
    """Return True when repo_root is inside a git work tree."""
    result = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def _git(args: list[str], repo_root: Path) -> str:
    """Run git in the repository and return its standard output."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise HockeyModelError(f"run git in {repo_root}: git is not installed") from exc
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or exc.stdout.strip()
        raise HockeyModelError(f"git {' '.join(args)} in {repo_root} failed: {detail}") from exc
    return result.stdout
