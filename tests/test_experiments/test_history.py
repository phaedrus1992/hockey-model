"""Tests for the git-history helpers of the experiment checker.

Covers:
- git failures: a missing binary and an unexpected git error are errors, not "untracked"
- deleted_record_ids in a repository with no commits and outside any repository
"""

import subprocess
from pathlib import Path

import pytest

from hockey_model.experiments import history
from hockey_model.experiments.history import deleted_record_ids, registration_commit
from hockey_model.types import HockeyModelError


def test_a_missing_git_binary_is_an_error(monkeypatch: pytest.MonkeyPatch, repo_root: Path) -> None:
    """Without git the checker says so, instead of reporting the record as untracked."""

    def no_git(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(history.subprocess, "run", no_git)
    with pytest.raises(HockeyModelError, match="git is not installed"):
        registration_commit("0001-valid", repo_root)


def test_an_unexpected_git_failure_is_an_error(
    monkeypatch: pytest.MonkeyPatch, repo_root: Path
) -> None:
    """A git error that is not "not a repository" stops the check, for example a bad owner."""

    def broken(args, **kwargs):
        return subprocess.CompletedProcess(args, 128, "", "fatal: detected dubious ownership")

    monkeypatch.setattr(history.subprocess, "run", broken)
    with pytest.raises(HockeyModelError, match="dubious ownership"):
        registration_commit("0001-valid", repo_root)


def test_a_directory_outside_a_repository_has_no_registration_commit(repo_root: Path) -> None:
    """A plain directory is not a work tree, so the record is simply untracked."""
    assert registration_commit("0001-valid", repo_root) is None


def test_deleted_record_ids_is_empty_outside_a_repository(repo_root: Path) -> None:
    """With no repository, no record counts as deleted."""
    assert deleted_record_ids([], repo_root) == []


def test_deleted_record_ids_is_empty_before_the_first_commit(repo_root: Path) -> None:
    """A repository with no commits has nothing tracked at HEAD."""
    subprocess.run(["git", "init"], cwd=repo_root, capture_output=True, check=True)
    assert deleted_record_ids([], repo_root) == []
