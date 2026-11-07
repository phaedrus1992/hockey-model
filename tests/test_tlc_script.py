"""Tests for scripts/tlc.sh. The tests use a fake curl or a fake jar, so no test downloads TLC."""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "tlc.sh"


def _run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
        env=env,
    )


def test_help_prints_usage_and_exits_zero() -> None:
    result = _run("--help")
    assert result.returncode == 0
    assert "Usage: bash scripts/tlc.sh" in result.stdout
    assert "Exit codes:" in result.stdout


def test_help_prints_the_whole_exit_code_block() -> None:
    assert "for a deadlock" in _run("--help").stdout


def test_unknown_argument_exits_two_and_names_it() -> None:
    result = _run("--bogus")
    assert result.returncode == 2
    assert "'--bogus'" in result.stderr


def test_extra_argument_exits_two_and_names_it() -> None:
    result = _run("--help", "extra")
    assert result.returncode == 2
    assert "'extra'" in result.stderr


def test_checksum_mismatch_deletes_jar_and_names_both_sums(tmp_path: Path) -> None:
    jar = tmp_path / "tla2tools-v1.7.4.jar"
    jar.write_bytes(b"not the tla tools jar")
    env = {**os.environ, "TLA_TOOLS_DIR": str(tmp_path)}
    result = _run(env=env)
    assert result.returncode == 1
    assert "checksum mismatch" in result.stderr
    assert "expected: 936a262061c9" in result.stderr
    assert "actual:" in result.stderr
    assert not jar.exists()


def test_failed_download_names_version_and_url(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_curl = bin_dir / "curl"
    fake_curl.write_text("#!/usr/bin/env bash\nexit 22\n", encoding="utf-8")
    fake_curl.chmod(0o755)
    jars = tmp_path / "jars"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "TLA_TOOLS_DIR": str(jars),
    }
    result = _run(env=env)
    assert result.returncode == 1
    assert "cannot download tla2tools v1.7.4 from https://github.com/tlaplus" in result.stderr
    assert not (jars / "tla2tools-v1.7.4.jar").exists()


def test_workers_flag_is_rejected() -> None:
    # TLC picks its own worker count, so the script has no --workers flag.
    result = _run("--workers")
    assert result.returncode == 2
    assert "'--workers'" in result.stderr
