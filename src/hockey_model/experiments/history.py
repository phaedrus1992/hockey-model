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
    if _git(["rev-parse", "--is-shallow-repository"], repo_root).strip() == "true":
        raise HockeyModelError(
            f"check {record_id!r}: {repo_root} is a shallow clone, so the registration "
            "commit is not visible; fetch the full history (for example fetch-depth: 0)"
        )
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
    # A stored blob holds lists where the record holds tuples, so compare as JSON.
    current = json.loads(json.dumps(record.to_dict().get("result")))
    for commit in _git(["log", "--format=%H", "--", relative], repo_root).split():
        prior = _result_at(commit, relative, repo_root)
        if prior is None:
            continue
        if prior != current:
            raise HockeyModelError(
                f"experiment {record.id!r}: commit {commit} recorded a result that the "
                "record no longer holds; a confirmation run is one-shot, so a new run "
                "needs a new record"
            )


def deleted_record_ids(present: list[str], repo_root: Path) -> list[str]:
    """Return the IDs of records that HEAD tracks but the working tree no longer holds.

    A deleted record could hide a spent look, so the checker treats it as an error.
    """
    if not _is_work_tree(repo_root):
        return []
    if (
        subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", "HEAD"], cwd=repo_root, capture_output=True
        ).returncode
        != 0
    ):
        return []
    names = _git(["ls-tree", "--name-only", "HEAD", f"{REGISTRY_DIR_NAME}/"], repo_root).split()
    tracked = {Path(name).stem for name in names if name.endswith(".json")}
    return sorted(tracked - set(present))


def _result_at(commit: str, relative: str, repo_root: Path) -> object:
    """Return the ``result`` field of a record as one commit stored it."""
    text = _git(["show", f"{commit}:{relative}"], repo_root)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise HockeyModelError(f"read {relative} at commit {commit}: invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise HockeyModelError(
            f"read {relative} at commit {commit}: a record must be a JSON object, "
            f"got a {type(data).__name__}"
        )
    return data.get("result")


def _is_work_tree(repo_root: Path) -> bool:
    """Return True when repo_root is inside a git work tree.

    A directory outside any repository is False. A missing git binary or any other
    git failure raises, so a broken git never passes as an untracked record.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise HockeyModelError(f"run git in {repo_root}: git is not installed") from exc
    if result.returncode == 0:
        return result.stdout.strip() == "true"
    if "not a git repository" in result.stderr:
        return False
    raise HockeyModelError(f"git rev-parse in {repo_root} failed: {result.stderr.strip()}")


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
