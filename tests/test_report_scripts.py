"""Tests for the report shell scripts, with fake `gh` and `uv` commands on PATH."""

import json
import os
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
DAY = "2026-11-04"
TAG = f"reports-{DAY}"


@pytest.fixture
def fakes(tmp_path: Path) -> Path:
    """Write fake `gh` and `uv` commands. Each records its arguments in calls.log."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(
        "#!/usr/bin/env bash\n"
        'echo "gh $*" >> "$FAKE_CALLS"\n'
        'if [[ "$1 $2" == "release list" ]]; then\n'
        '  if [[ -n "${FAKE_GH_FAIL:-}" ]]; then echo "auth failed" >&2; exit 4; fi\n'
        '  printf "%s" "${FAKE_RELEASES:-}"\n'
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    uv = bin_dir / "uv"
    uv.write_text(
        '#!/usr/bin/env bash\necho "uv $*" >> "$FAKE_CALLS"\nprintf "%s" "$FAKE_DUE_JSON"\n',
        encoding="utf-8",
    )
    for command in (gh, uv):
        command.chmod(0o755)
    return bin_dir


def _env(fakes: Path, tmp_path: Path, **extra: str) -> dict[str, str]:
    env = {
        "PATH": f"{fakes}{os.pathsep}{os.environ['PATH']}",
        "FAKE_CALLS": str(tmp_path / "calls.log"),
        "FAKE_RELEASES": "",
        "FAKE_DUE_JSON": json.dumps({"due": True, "tag": TAG, "forced": False}),
    }
    env.update(extra)
    return env


def _calls(tmp_path: Path) -> list[str]:
    log = tmp_path / "calls.log"
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def _run(script: str, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPTS / script), *args],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


# --- gate ---------------------------------------------------------------------


def test_gate_due_and_not_published_publishes(fakes: Path, tmp_path: Path) -> None:
    result = _run("report-gate.sh", _env(fakes, tmp_path), "--date", DAY)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"due": True, "tag": TAG, "reason": "due"}


def test_gate_skips_a_day_that_is_already_published(fakes: Path, tmp_path: Path) -> None:
    env = _env(fakes, tmp_path, FAKE_RELEASES=f"reports-2026-11-03\n{TAG}\n")
    result = _run("report-gate.sh", env, "--date", DAY)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["reason"] == "already-published"
    assert json.loads(result.stdout)["due"] is False


def test_gate_does_not_match_a_tag_prefix(fakes: Path, tmp_path: Path) -> None:
    env = _env(fakes, tmp_path, FAKE_RELEASES="reports-2026-11-04-old\n")
    result = _run("report-gate.sh", env, "--date", DAY)
    assert json.loads(result.stdout)["due"] is True


def test_gate_not_due_skips_the_release_lookup(fakes: Path, tmp_path: Path) -> None:
    due = json.dumps({"due": False, "tag": TAG, "forced": False})
    result = _run("report-gate.sh", _env(fakes, tmp_path, FAKE_DUE_JSON=due), "--date", DAY)
    assert json.loads(result.stdout) == {"due": False, "tag": TAG, "reason": "not-due"}
    assert not any(line.startswith("gh ") for line in _calls(tmp_path))


def test_gate_forwards_force(fakes: Path, tmp_path: Path) -> None:
    _run("report-gate.sh", _env(fakes, tmp_path), "--date", DAY, "--force")
    assert f"uv run hockey-model report-due --date {DAY} --force" in _calls(tmp_path)


def test_gate_fails_when_the_release_lookup_fails(fakes: Path, tmp_path: Path) -> None:
    result = _run("report-gate.sh", _env(fakes, tmp_path, FAKE_GH_FAIL="1"), "--date", DAY)
    assert result.returncode != 0
    assert result.stdout == ""
    assert "auth failed" in result.stderr


def test_gate_rejects_an_unknown_argument(fakes: Path, tmp_path: Path) -> None:
    result = _run("report-gate.sh", _env(fakes, tmp_path), "--bogus")
    assert result.returncode == 2
    assert "unknown argument" in result.stderr


# --- publish ------------------------------------------------------------------


def _write_report(report_dir: Path) -> None:
    report_dir.mkdir()
    (report_dir / f"report-{DAY}.md").write_text("# report\n", encoding="utf-8")
    (report_dir / f"report-{DAY}.json").write_text("{}\n", encoding="utf-8")


def test_publish_creates_the_release_with_the_day_tag(fakes: Path, tmp_path: Path) -> None:
    _write_report(tmp_path / "report")
    args = ("--date", DAY, "--report-dir", str(tmp_path / "report"))
    result = _run("publish-daily-report.sh", _env(fakes, tmp_path), *args)
    assert result.returncode == 0, result.stderr
    create = [line for line in _calls(tmp_path) if line.startswith("gh release create")]
    assert create and f" {TAG} " in create[0]


def test_publish_refuses_a_day_that_already_has_a_release(fakes: Path, tmp_path: Path) -> None:
    _write_report(tmp_path / "report")
    env = _env(fakes, tmp_path, FAKE_RELEASES=f"{TAG}\n")
    args = ("--date", DAY, "--report-dir", str(tmp_path / "report"))
    result = _run("publish-daily-report.sh", env, *args)
    assert result.returncode == 1
    assert f"release {TAG} already exists" in result.stderr
    assert not any(line.startswith("gh release create") for line in _calls(tmp_path))


def test_publish_refuses_a_missing_report(fakes: Path, tmp_path: Path) -> None:
    (tmp_path / "report").mkdir()
    args = ("--date", DAY, "--report-dir", str(tmp_path / "report"))
    result = _run("publish-daily-report.sh", _env(fakes, tmp_path), *args)
    assert result.returncode == 1
    assert "missing or empty" in result.stderr
    assert not any(line.startswith("gh release create") for line in _calls(tmp_path))


def test_publish_refuses_an_empty_report(fakes: Path, tmp_path: Path) -> None:
    _write_report(tmp_path / "report")
    (tmp_path / "report" / f"report-{DAY}.json").write_text("", encoding="utf-8")
    args = ("--date", DAY, "--report-dir", str(tmp_path / "report"))
    result = _run("publish-daily-report.sh", _env(fakes, tmp_path), *args)
    assert result.returncode == 1
    assert "missing or empty" in result.stderr


# --- daily run ----------------------------------------------------------------


def test_daily_run_needs_the_store_path(fakes: Path, tmp_path: Path) -> None:
    result = _run("daily-report.sh", _env(fakes, tmp_path), "--date", DAY, "--out-dir", "x")
    assert result.returncode == 2
    assert "HOCKEY_MODEL_DB" in result.stderr


def test_daily_run_needs_a_date(fakes: Path, tmp_path: Path) -> None:
    env = _env(fakes, tmp_path, HOCKEY_MODEL_DB=str(tmp_path / "s.db"))
    result = _run("daily-report.sh", env, "--out-dir", "x")
    assert result.returncode == 2
    assert "--date and --out-dir are required" in result.stderr
