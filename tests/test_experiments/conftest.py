"""Shared fixtures for the experiment registry tests."""

from pathlib import Path

import pytest

import hockey_model.experiments.check as check_module
import hockey_model.experiments.registry as registry_module

# The real schema files, copied so the tests validate against the shipped schemas.
_SCHEMA_FILES = ("schema.json", "check_output.schema.json")


@pytest.fixture
def registry_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the registry at a temporary directory holding copies of the real schemas."""
    reg_dir = tmp_path / "experiments"
    reg_dir.mkdir()
    for name in _SCHEMA_FILES:
        text = (Path("experiments") / name).read_text(encoding="utf-8")
        (reg_dir / name).write_text(text, encoding="utf-8")
    for module in (registry_module, check_module):
        monkeypatch.setattr(module, "REGISTRY_DIR", reg_dir)
        monkeypatch.setattr(module, "SCHEMA_PATH", reg_dir / "schema.json")
        monkeypatch.setattr(
            module, "CHECK_OUTPUT_SCHEMA_PATH", reg_dir / "check_output.schema.json"
        )
        monkeypatch.setattr(module, "RESULTS_DIR", reg_dir / "results")
    return reg_dir
