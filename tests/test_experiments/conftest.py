"""Shared fixtures for the experiment registry tests."""

from pathlib import Path

import pytest

from hockey_model.experiments.registry import REGISTRY_DIR_NAME


@pytest.fixture
def repo_root(tmp_path: Path) -> Path:
    """Return a repository root with an empty experiment registry.

    The schemas are Python constants in the package, so a test registry needs no
    schema files.
    """
    (tmp_path / REGISTRY_DIR_NAME).mkdir()
    return tmp_path


@pytest.fixture
def registry_dir(repo_root: Path) -> Path:
    """Return the registry directory inside the fixture repository."""
    return repo_root / REGISTRY_DIR_NAME
