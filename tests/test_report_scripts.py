"""Tests for the report shell scripts, with fake `gh` and `uv` commands on PATH."""

import json
import os
import subprocess
from pathlib import Path

import pytest

# The mutation run copies src and tests only, so the scripts are not there to test.
if "mutants" in Path(__file__).resolve().parts:
    pytest.skip("the mutation copy has no scripts directory", allow_module_level=True)

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
DAY = "2026-11-04"
TAG = f"reports-{DAY}"
SHA = "0123456789abcdef0123456789abcdef01234567"


@pytest.fixture
def fakes(tmp_path: Path) -> Path:
    """Write fake `gh` and `uv` commands. Each records its arguments in calls.log.

    `gh release view TAG` succeeds for a tag in FAKE_RELEASES and otherwise prints
    "release not found", as the real command does. `gh release create` refuses a tag that
    already exists. FAKE_GH_FAIL makes every gh call fail with an auth error.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(
        "#!/usr/bin/env bash\n"
        'echo "gh $*" >> "$FAKE_CALLS"\n'
        'if [[ -n "${FAKE_GH_FAIL:-}" ]]; then echo "auth failed" >&2; exit 4; fi\n'
        'tag="${3:-}"\n'
        'if [[ "$1 $2" == "release view" ]]; then\n'
        '  if grep -qxF "$tag" <<<"${FAKE_RELEASES:-}"; then exit 0; fi\n'
        '  echo "release not found" >&2\n'
        "  exit 1\n"
        "fi\n"
        'if [[ "$1 $2" == "release create" ]]; then\n'
        '  if grep -qxF "$3" <<<"${FAKE_RELEASES:-}"; then\n'
        '    echo "a release with the same tag name already exists" >&2\n'
        "    exit 1\n"
        "  fi\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    uv = bin_dir / "uv"
    uv.write_text(
        '#!/usr/bin/env bash\necho "uv $*" >> "$FAKE_CALLS"\n'
        'if [[ "$*" == "run hockey-model report-due"* ]]; then printf "%s" "$FAKE_DUE_JSON"; fi\n'
        "exit 0\n",
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
        "FAKE_DUE_JSON": json.dumps({"due": True, "tag": TAG, "date": DAY, "games": 3}),
        "GITHUB_SHA": SHA,
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
    assert json.loads(result.stdout) == {"due": True, "tag": TAG, "reason": "due", "date": DAY}


def test_gate_skips_a_day_that_is_already_published(fakes: Path, tmp_path: Path) -> None:
    env = _env(fakes, tmp_path, FAKE_RELEASES=f"reports-2026-11-03\n{TAG}\n")
    result = _run("report-gate.sh", env, "--date", DAY)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "due": False,
        "tag": TAG,
        "reason": "already-published",
        "date": DAY,
    }


def test_gate_not_due_skips_the_release_lookup(fakes: Path, tmp_path: Path) -> None:
    due = json.dumps({"due": False, "tag": TAG, "date": DAY, "games": 3})
    result = _run("report-gate.sh", _env(fakes, tmp_path, FAKE_DUE_JSON=due), "--date", DAY)
    assert json.loads(result.stdout) == {"due": False, "tag": TAG, "reason": "not-due", "date": DAY}
    assert not any(line.startswith("gh ") for line in _calls(tmp_path))


def test_gate_without_a_date_lets_report_due_pick_the_game_day(fakes: Path, tmp_path: Path) -> None:
    result = _run("report-gate.sh", _env(fakes, tmp_path))
    assert result.returncode == 0, result.stderr
    assert "uv run hockey-model report-due" in _calls(tmp_path)
    assert json.loads(result.stdout)["date"] == DAY


def test_gate_forwards_force(fakes: Path, tmp_path: Path) -> None:
    _run("report-gate.sh", _env(fakes, tmp_path), "--date", DAY, "--force")
    assert f"uv run hockey-model report-due --date {DAY} --force" in _calls(tmp_path)


def test_gate_fails_when_the_release_lookup_fails_for_another_reason(
    fakes: Path, tmp_path: Path
) -> None:
    result = _run("report-gate.sh", _env(fakes, tmp_path, FAKE_GH_FAIL="1"), "--date", DAY)
    assert result.returncode != 0
    assert result.stdout == ""
    assert "auth failed" in result.stderr


def test_gate_fails_on_a_payload_without_the_gate_fields(fakes: Path, tmp_path: Path) -> None:
    bad = json.dumps({"due": "yes", "tag": TAG, "date": DAY, "games": 3})
    result = _run("report-gate.sh", _env(fakes, tmp_path, FAKE_DUE_JSON=bad), "--date", DAY)
    assert result.returncode == 1
    assert "lacks due, tag, games, or date" in result.stderr


def test_gate_warns_when_the_schedule_is_empty(fakes: Path, tmp_path: Path) -> None:
    empty = json.dumps({"due": False, "tag": TAG, "date": DAY, "games": 0})
    result = _run("report-gate.sh", _env(fakes, tmp_path, FAKE_DUE_JSON=empty), "--date", DAY)
    assert result.returncode == 0
    assert "::warning::" in result.stderr


def test_gate_rejects_an_unknown_argument(fakes: Path, tmp_path: Path) -> None:
    result = _run("report-gate.sh", _env(fakes, tmp_path), "--bogus")
    assert result.returncode == 2
    assert "unknown argument" in result.stderr


def test_gate_help_names_every_option(fakes: Path, tmp_path: Path) -> None:
    result = _run("report-gate.sh", _env(fakes, tmp_path), "--help")
    assert result.returncode == 0
    assert "--date" in result.stdout and "--force" in result.stdout
    assert "set -euo" not in result.stdout


# --- publish ------------------------------------------------------------------


def _write_report(report_dir: Path) -> None:
    report_dir.mkdir()
    (report_dir / f"report-{DAY}.md").write_text("# report\n", encoding="utf-8")
    (report_dir / f"report-{DAY}.json").write_text("{}\n", encoding="utf-8")
    (report_dir / f"backtest-{DAY}.json").write_text("{}\n", encoding="utf-8")
    (report_dir / f"backtest-games-{DAY}.csv").write_text("game_id,elo\n1,1\n", encoding="utf-8")


def _publish(fakes: Path, tmp_path: Path, **extra: str) -> subprocess.CompletedProcess[str]:
    args = ("--date", DAY, "--report-dir", str(tmp_path / "report"))
    return _run("publish-daily-report.sh", _env(fakes, tmp_path, **extra), *args)


def test_publish_creates_the_release_at_the_build_commit(fakes: Path, tmp_path: Path) -> None:
    _write_report(tmp_path / "report")
    result = _publish(fakes, tmp_path)
    assert result.returncode == 0, result.stderr
    create = [line for line in _calls(tmp_path) if line.startswith("gh release create")]
    assert create and f" {TAG} " in create[0]
    assert f"--target {SHA}" in create[0]
    assert create[0].count("backtest") == 2


def test_publish_refuses_a_day_that_already_has_a_release(fakes: Path, tmp_path: Path) -> None:
    _write_report(tmp_path / "report")
    result = _publish(fakes, tmp_path, FAKE_RELEASES=f"{TAG}\n")
    assert result.returncode == 1
    assert "already exists" in result.stderr


def test_publish_needs_the_build_commit(fakes: Path, tmp_path: Path) -> None:
    _write_report(tmp_path / "report")
    env = _env(fakes, tmp_path)
    del env["GITHUB_SHA"]
    args = ("--date", DAY, "--report-dir", str(tmp_path / "report"))
    result = _run("publish-daily-report.sh", env, *args)
    assert result.returncode == 2
    assert "GITHUB_SHA" in result.stderr


@pytest.mark.parametrize("bad", ["../2026-11-04", "2026-11-04 extra", "2026-1-4", "tomorrow"])
def test_publish_refuses_a_malformed_date(fakes: Path, tmp_path: Path, bad: str) -> None:
    _write_report(tmp_path / "report")
    args = ("--date", bad, "--report-dir", str(tmp_path / "report"))
    result = _run("publish-daily-report.sh", _env(fakes, tmp_path), *args)
    assert result.returncode == 2
    assert "must be YYYY-MM-DD" in result.stderr
    assert not any(line.startswith("gh release create") for line in _calls(tmp_path))


def test_publish_refuses_a_missing_report(fakes: Path, tmp_path: Path) -> None:
    (tmp_path / "report").mkdir()
    result = _publish(fakes, tmp_path)
    assert result.returncode == 1
    assert "missing or empty" in result.stderr
    assert not any(line.startswith("gh release create") for line in _calls(tmp_path))


def test_publish_refuses_an_empty_report(fakes: Path, tmp_path: Path) -> None:
    _write_report(tmp_path / "report")
    (tmp_path / "report" / f"report-{DAY}.json").write_text("", encoding="utf-8")
    result = _publish(fakes, tmp_path)
    assert result.returncode == 1
    assert "missing or empty" in result.stderr


def test_publish_refuses_invalid_json(fakes: Path, tmp_path: Path) -> None:
    _write_report(tmp_path / "report")
    (tmp_path / "report" / f"backtest-{DAY}.json").write_text("<html>", encoding="utf-8")
    result = _publish(fakes, tmp_path)
    assert result.returncode == 1
    assert "is not valid JSON" in result.stderr
    assert not any(line.startswith("gh release create") for line in _calls(tmp_path))


def test_publish_refuses_a_csv_without_a_header(fakes: Path, tmp_path: Path) -> None:
    _write_report(tmp_path / "report")
    (tmp_path / "report" / f"backtest-games-{DAY}.csv").write_text("Not Found\n", encoding="utf-8")
    result = _publish(fakes, tmp_path)
    assert result.returncode == 1
    assert "no CSV header" in result.stderr


def test_publish_help_names_the_delete_first_step(fakes: Path, tmp_path: Path) -> None:
    result = _run("publish-daily-report.sh", _env(fakes, tmp_path), "--help")
    assert result.returncode == 0
    assert "Delete the" in result.stdout
    assert "--report-dir" in result.stdout


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


def test_daily_run_backfills_until_the_marker_exists(fakes: Path, tmp_path: Path) -> None:
    db = tmp_path / "store" / "store.db"
    env = _env(fakes, tmp_path, HOCKEY_MODEL_DB=str(db))
    args = ("--date", DAY, "--out-dir", str(tmp_path / "out"))
    first = _run("daily-report.sh", env, *args)
    assert first.returncode == 0, first.stderr
    assert "backfilling from 2014-10-01" in first.stderr
    assert (tmp_path / "store" / "store.db.backfilled").exists()

    _run("daily-report.sh", env, *args)
    refreshes = [line for line in _calls(tmp_path) if "refresh" in line]
    assert refreshes == [
        "uv run hockey-model refresh --backfill-from 2014-10-01",
        "uv run hockey-model refresh",
    ]


def test_daily_run_resumes_a_partial_backfill(fakes: Path, tmp_path: Path) -> None:
    db = tmp_path / "store" / "store.db"
    db.parent.mkdir()
    db.write_text("partial", encoding="utf-8")
    env = _env(fakes, tmp_path, HOCKEY_MODEL_DB=str(db))
    result = _run("daily-report.sh", env, "--date", DAY, "--out-dir", str(tmp_path / "out"))
    assert result.returncode == 0, result.stderr
    assert "uv run hockey-model refresh --backfill-from 2014-10-01" in _calls(tmp_path)


def test_daily_run_stops_at_a_failed_refresh(fakes: Path, tmp_path: Path) -> None:
    db = tmp_path / "store" / "store.db"
    env = _env(fakes, tmp_path, HOCKEY_MODEL_DB=str(db))
    failing = fakes / "uv"
    failing.write_text(
        '#!/usr/bin/env bash\necho "uv $*" >> "$FAKE_CALLS"\n'
        'if [[ "$*" == *refresh* ]]; then exit 1; fi\nexit 0\n',
        encoding="utf-8",
    )
    failing.chmod(0o755)
    result = _run("daily-report.sh", env, "--date", DAY, "--out-dir", str(tmp_path / "out"))
    assert result.returncode == 1
    assert not any("daily --date" in line for line in _calls(tmp_path))
    assert not (tmp_path / "store" / "store.db.backfilled").exists()


def test_daily_help_documents_the_marker(fakes: Path, tmp_path: Path) -> None:
    result = _run("daily-report.sh", _env(fakes, tmp_path), "--help")
    assert result.returncode == 0
    assert "resumes on the next run" in result.stdout
