"""Tests for the mutation shard table and merge in scripts/mutation_shards.py."""

import importlib.util
import json
from fnmatch import fnmatch
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "mutation_shards.py"


def _load_shards() -> ModuleType:
    """Import the script by path, because scripts/ is not a package."""
    if not SCRIPT.exists():
        # A mutation run copies src/ and tests/ only, so the script is absent there.
        pytest.skip("scripts/mutation_shards.py is not copied", allow_module_level=True)
    spec = importlib.util.spec_from_file_location("mutation_shards", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


shards = _load_shards()


def test_shard_patterns_return_one_glob_per_module() -> None:
    assert shards.shard_patterns(0) == ("hockey_model.sources.http.*",)
    assert "hockey_model.sources.errors.*" in shards.shard_patterns(1)


def test_every_covered_module_has_exactly_one_owning_shard() -> None:
    covered = shards.covered_modules(ROOT / "pyproject.toml")
    for module in covered:
        key = f"{shards.MUTANT_PREFIX}{module}.parse__mutmut_1"
        owners = [
            index
            for index in range(len(shards.SHARDS))
            if any(fnmatch(key, glob) for glob in shards.shard_patterns(index))
        ]
        assert len(owners) == 1, f"{key} matched shards {owners}"


@pytest.mark.parametrize("index", [-1, len(shards.SHARDS)])
def test_shard_patterns_reject_an_index_outside_the_table(index: int) -> None:
    with pytest.raises(shards.ShardError, match="does not exist"):
        shards.shard_patterns(index)


@pytest.mark.parametrize(
    ("path", "module"),
    [
        ("src/hockey_model/sources/nhl.py", "sources.nhl"),
        ("src/hockey_model/backtest/metrics.py", "backtest.metrics"),
        ("src/hockey_model/game_model/elo.py", "game_model.elo"),
    ],
)
def test_module_from_source_drops_the_package_prefix(path: str, module: str) -> None:
    assert shards.module_from_source(path) == module


@pytest.mark.parametrize("path", ["tests/test_x.py", "src/hockey_model/x.txt"])
def test_module_from_source_rejects_a_path_outside_src(path: str) -> None:
    with pytest.raises(shards.ShardError, match="src/ Python file"):
        shards.module_from_source(path)


def test_the_shards_cover_the_configured_modules_exactly_once() -> None:
    covered = shards.covered_modules(ROOT / "pyproject.toml")
    assert shards.check_partition(covered) == []


def test_check_partition_reports_an_uncovered_module() -> None:
    covered = {"backtest.metrics", "game_model.elo", "brand.new"}
    problems = shards.check_partition(covered)
    assert any("brand.new is covered but in no shard" in p for p in problems)


def test_check_partition_reports_a_module_listed_twice(monkeypatch: pytest.MonkeyPatch) -> None:
    doubled = (*shards.SHARDS, ("backtest.metrics",))
    monkeypatch.setattr(shards, "SHARDS", doubled)
    problems = shards.check_partition(shards.covered_modules(ROOT / "pyproject.toml"))
    assert problems == ["backtest.metrics is in more than one shard"]


def _write_meta(path: Path, codes: dict[str, object], **extra: object) -> None:
    """Write a .meta file with the given exit codes, the way a shard leaves it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"exit_code_by_key": codes, "hash_by_function_name": {"f": "abc"}, **extra}
    path.write_text(json.dumps(doc), encoding="utf-8")


def _read_codes(path: Path) -> dict[str, object]:
    """Return the exit_code_by_key of one .meta file."""
    return json.loads(path.read_text(encoding="utf-8"))["exit_code_by_key"]


def test_merge_meta_unions_the_mutants_each_shard_ran(tmp_path: Path) -> None:
    first = tmp_path / "shard-0"
    second = tmp_path / "shard-1"
    _write_meta(first / "src/a.py.meta", {"m.x__1": 0, "m.x__2": None})
    _write_meta(second / "src/a.py.meta", {"m.x__1": None, "m.x__2": 1})
    dest = tmp_path / "merged"

    written = shards.merge_meta([first, second], dest)

    assert written == 1
    assert _read_codes(dest / "src/a.py.meta") == {"m.x__1": 0, "m.x__2": 1}


def test_merge_meta_keeps_a_file_only_one_shard_wrote(tmp_path: Path) -> None:
    first = tmp_path / "shard-0"
    second = tmp_path / "shard-1"
    _write_meta(first / "src/a.py.meta", {"m.x__1": 0})
    _write_meta(second / "src/b.py.meta", {"m.y__1": None})

    assert shards.merge_meta([first, second], tmp_path / "merged") == 2


def test_merge_meta_rejects_two_results_for_one_mutant(tmp_path: Path) -> None:
    first = tmp_path / "shard-0"
    second = tmp_path / "shard-1"
    _write_meta(first / "src/a.py.meta", {"m.x__1": 0})
    _write_meta(second / "src/a.py.meta", {"m.x__1": 1})
    with pytest.raises(shards.ShardError, match="two results"):
        shards.merge_meta([first, second], tmp_path / "merged")


def test_merge_meta_rejects_shards_that_ran_different_source(tmp_path: Path) -> None:
    first = tmp_path / "shard-0"
    second = tmp_path / "shard-1"
    _write_meta(first / "src/a.py.meta", {"m.x__1": None})
    doc = {"exit_code_by_key": {"m.x__1": None}, "hash_by_function_name": {"f": "other"}}
    (second / "src").mkdir(parents=True)
    (second / "src/a.py.meta").write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(shards.ShardError, match="source hashes"):
        shards.merge_meta([first, second], tmp_path / "merged")
