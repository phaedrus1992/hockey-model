"""Tests for the pre-push mutation selector, on temporary git repos and a stub mutmut."""

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

# The mutation run copies src and tests only, so the scripts are not there to test.
if "mutants" in Path(__file__).resolve().parts:
    pytest.skip("the mutation copy has no scripts directory", allow_module_level=True)

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "pre_push_mutation.py"
SOURCE = "src/hockey_model/sources/shapes.py"
BASE_SOURCE = (
    "def top(x):\n"  # line 1
    "    return x + 1\n"  # line 2
    "\n"
    "\n"
    "class Box:\n"  # line 5
    "    size = 1\n"
    "\n"
    "    def grow(self, n):\n"  # line 8
    "        return self.size + n\n"  # line 9
)
PYPROJECT = '[tool.mutmut]\nonly_mutate = ["src/hockey_model/sources/*.py"]\n'


@pytest.fixture(scope="module")
def mod() -> ModuleType:
    spec = importlib.util.spec_from_file_location("pre_push_mutation", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["pre_push_mutation"] = module
    spec.loader.exec_module(module)
    return module


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        [
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.com",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout


def _commit(repo: Path, files: dict[str, str | None], message: str) -> None:
    for path, text in files.items():
        target = repo / path
        if text is None:
            target.unlink()
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repo whose base commit is the default branch on origin, with a feature commit on top."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _commit(root, {"pyproject.toml": PYPROJECT, SOURCE: BASE_SOURCE}, "base")
    _git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(root, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
    return root


def test_first_push_uses_the_remote_default_branch_as_base(mod: ModuleType, repo: Path) -> None:
    base_sha = _git(repo, "rev-parse", "HEAD").strip()
    _commit(repo, {SOURCE: BASE_SOURCE.replace("+ 1", "+ 2")}, "feature")
    assert mod.resolve_base(repo) == base_sha


def test_missing_origin_head_fails_with_the_fix(mod: ModuleType, repo: Path) -> None:
    _git(repo, "symbolic-ref", "--delete", "refs/remotes/origin/HEAD")
    with pytest.raises(mod.PushCheckError, match="git remote set-head origin --auto"):
        mod.resolve_base(repo)


def test_upstream_branch_is_the_base_when_it_is_set(mod: ModuleType, repo: Path) -> None:
    _git(repo, "update-ref", "refs/remotes/origin/feat", "HEAD")
    _git(repo, "config", "branch.main.remote", "origin")
    _git(repo, "config", "branch.main.merge", "refs/heads/feat")
    upstream_sha = _git(repo, "rev-parse", "HEAD").strip()
    _commit(repo, {SOURCE: BASE_SOURCE.replace("+ 1", "+ 2")}, "feature")
    assert mod.resolve_base(repo) == upstream_sha


def test_a_rename_is_a_delete_and_an_add(mod: ModuleType, repo: Path) -> None:
    _git(repo, "mv", SOURCE, "src/hockey_model/sources/renamed.py")
    _git(repo, "commit", "-q", "-m", "rename")
    changes = mod.changed_files(repo, mod.resolve_base(repo))
    assert mod.FileChange("D", SOURCE) in changes
    assert mod.FileChange("A", "src/hockey_model/sources/renamed.py") in changes


def test_changed_lines_cover_an_edit_and_mark_a_pure_deletion(mod: ModuleType, repo: Path) -> None:
    base = mod.resolve_base(repo)
    _commit(repo, {SOURCE: BASE_SOURCE.replace("+ 1", "+ 2")}, "edit")
    assert mod.changed_lines(repo, base, SOURCE) == {2}
    kept = BASE_SOURCE.replace("+ 1", "+ 2").replace("    size = 1\n", "")
    _commit(repo, {SOURCE: kept}, "delete")
    assert mod.changed_lines(repo, base, SOURCE) == {2, 5}


def test_targets_are_top_level_functions_and_methods_only(mod: ModuleType) -> None:
    lines = {2, 9}
    targets = mod.targets_at(BASE_SOURCE, lines)
    assert [t.qualname for t in targets] == ["top", "Box.grow"]
    assert targets[1].def_line == 8


def test_a_decorator_line_belongs_to_its_function(mod: ModuleType) -> None:
    source = "@staticmethod\ndef f():\n    return 1\n"
    (target,) = mod.targets_at(source, {1})
    assert (target.qualname, target.def_line, target.first_line) == ("f", 2, 1)


def test_a_class_attribute_line_selects_nothing(mod: ModuleType) -> None:
    assert mod.targets_at(BASE_SOURCE, {6}) == []


def test_mutant_globs_use_the_mutmut_names(mod: ModuleType) -> None:
    assert mod.mutant_glob(SOURCE, "top") == "hockey_model.sources.shapes.x_top__mutmut_*"
    assert mod.mutant_glob(SOURCE, "Box.grow") == (
        "hockey_model.sources.shapes.xǁBoxǁgrow__mutmut_*"
    )


def test_show_diff_lines_are_function_relative(mod: ModuleType) -> None:
    diff = (
        "# hockey_model.x.top__mutmut_1: survived\n"
        "--- src/hockey_model/x.py\n+++ src/hockey_model/x.py\n"
        "@@ -1,3 +1,3 @@\n def top(x):\n-    return x + 1\n+    return x + 2\n"
    )
    assert mod.mutated_original_lines(diff) == {2}


@pytest.mark.parametrize("bad", ["just words", "name:status-but-no-space"])
def test_a_malformed_result_line_fails(mod: ModuleType, bad: str) -> None:
    with pytest.raises(mod.PushCheckError, match="not a result"):
        mod.parse_results(bad + "\n")


def test_a_directory_that_is_not_mutmut_output_is_kept(mod: ModuleType, repo: Path) -> None:
    (repo / "mutants").mkdir()
    (repo / "mutants" / "keep.txt").write_text("mine", encoding="utf-8")
    with pytest.raises(mod.PushCheckError, match="not mutmut output"):
        mod.clear_generated_mutants(repo)
    assert (repo / "mutants" / "keep.txt").exists()


def test_generated_mutants_are_removed(mod: ModuleType, repo: Path) -> None:
    (repo / "mutants").mkdir()
    (repo / "mutants" / "mutmut-stats.json").write_text("{}", encoding="utf-8")
    (repo / "mutants" / "pyproject.toml").write_text("", encoding="utf-8")
    mod.clear_generated_mutants(repo)
    assert not (repo / "mutants").exists()


@pytest.fixture
def fake_mutmut(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A stub mutmut. Its output comes from the FAKE_* environment variables."""
    stub = tmp_path / "fake-mutmut"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        'case "$1" in\n'
        '  run) echo "run $*" >> "$FAKE_CALLS"; sleep "${FAKE_SLEEP:-0}";'
        '    exit "${FAKE_RUN_RC:-0}";;\n'
        '  results) printf "%s" "$FAKE_RESULTS";;\n'
        '  show) printf "%s" "$FAKE_SHOW";;\n'
        "esac\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    monkeypatch.setenv("PRE_PUSH_MUTMUT", str(stub))
    monkeypatch.setenv("FAKE_CALLS", str(tmp_path / "calls.log"))
    monkeypatch.setenv("FAKE_RESULTS", "")
    monkeypatch.setenv("FAKE_SHOW", "")
    return stub


def _changed_top(repo: Path) -> None:
    _commit(repo, {SOURCE: BASE_SOURCE.replace("+ 1", "+ 2")}, "change top")


TOP = "hockey_model.sources.shapes.x_top__mutmut_1"
GROW_SURVIVED_OFF_LINE = (
    "# x\n--- src/hockey_model/sources/shapes.py\n+++ src/hockey_model/sources/shapes.py\n"
    "@@ -1,2 +1,2 @@\n-def top(x):\n+def top(x, y):\n     return x + 2\n"
)
SURVIVED_ON_LINE = (
    "# x\n--- src/hockey_model/sources/shapes.py\n+++ src/hockey_model/sources/shapes.py\n"
    "@@ -1,2 +1,2 @@\n def top(x):\n-    return x + 2\n+    return x + 3\n"
)


def test_a_killed_mutant_passes(
    mod: ModuleType, repo: Path, fake_mutmut: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _changed_top(repo)
    monkeypatch.setenv("FAKE_RESULTS", f"    {TOP}: killed\n")
    assert mod.run_check(repo) == 0


def test_a_survivor_on_a_changed_line_fails(
    mod: ModuleType, repo: Path, fake_mutmut: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _changed_top(repo)
    monkeypatch.setenv("FAKE_RESULTS", f"    {TOP}: survived\n")
    monkeypatch.setenv("FAKE_SHOW", SURVIVED_ON_LINE)
    assert mod.run_check(repo) == 1


def test_a_survivor_off_the_changed_line_passes(
    mod: ModuleType, repo: Path, fake_mutmut: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _changed_top(repo)
    monkeypatch.setenv("FAKE_RESULTS", f"    {TOP}: survived\n")
    monkeypatch.setenv("FAKE_SHOW", GROW_SURVIVED_OFF_LINE)
    assert mod.run_check(repo) == 0


@pytest.mark.parametrize("status", ["timeout", "not checked", "skipped", "weird"])
def test_an_incomplete_or_unknown_status_fails(
    mod: ModuleType, repo: Path, fake_mutmut: Path, monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    _changed_top(repo)
    monkeypatch.setenv("FAKE_RESULTS", f"    {TOP}: {status}\n")
    assert mod.run_check(repo) == 1


def test_no_mutant_for_a_changed_function_fails(
    mod: ModuleType, repo: Path, fake_mutmut: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _changed_top(repo)
    monkeypatch.setenv("FAKE_RESULTS", "    hockey_model.other.f__mutmut_1: killed\n")
    assert mod.run_check(repo) == 1


def test_a_failed_mutmut_run_fails(
    mod: ModuleType, repo: Path, fake_mutmut: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _changed_top(repo)
    monkeypatch.setenv("FAKE_RUN_RC", "3")
    with pytest.raises(mod.PushCheckError, match="exited 3"):
        mod.run_mutmut(repo, ["run", TOP])


def test_a_run_past_the_timeout_fails_with_the_fix(
    mod: ModuleType, repo: Path, fake_mutmut: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _changed_top(repo)
    monkeypatch.setattr(mod, "MUTMUT_TIMEOUT_S", 0.5)
    monkeypatch.setenv("FAKE_SLEEP", "5")
    with pytest.raises(mod.PushCheckError, match="stopped"):
        mod.run_mutmut(repo, ["run", TOP])


def test_a_docs_only_push_runs_no_mutants(
    mod: ModuleType, repo: Path, fake_mutmut: Path, tmp_path: Path
) -> None:
    _commit(repo, {"README.md": "hello\n"}, "docs")
    assert mod.run_check(repo) == 0
    assert not (tmp_path / "calls.log").exists()


def test_a_test_only_push_runs_no_mutants(
    mod: ModuleType, repo: Path, fake_mutmut: Path, tmp_path: Path
) -> None:
    _commit(repo, {"tests/test_shapes.py": "def test_x():\n    pass\n"}, "test")
    assert mod.run_check(repo) == 0
    assert not (tmp_path / "calls.log").exists()


def test_a_dirty_tree_is_refused(mod: ModuleType, repo: Path, fake_mutmut: Path) -> None:
    _changed_top(repo)
    (repo / SOURCE).write_text("# edited\n", encoding="utf-8")
    with pytest.raises(mod.PushCheckError, match="uncommitted changes"):
        mod.clean_worktree(repo)
