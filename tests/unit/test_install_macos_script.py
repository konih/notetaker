"""F5: packaging/install-macos.sh — hermetic smoke tests via PATH shims + --dry-run.

The script must never execute package managers in these tests: every external
command (uname, brew, uv, ffmpeg, xcode-select, live-transcriber) is a shim on a
prepended PATH, and mutating steps only run behind ``--dry-run`` guards, so the
suite stays hermetic on Linux CI (no brew, no Darwin) and on developer Macs.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "packaging" / "install-macos.sh"


def _make_shim(bin_dir: Path, name: str, body: str) -> None:
    shim = bin_dir / name
    shim.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


@pytest.fixture()
def shim_env(tmp_path: Path) -> dict[str, str]:
    """Environment where uname says Darwin/arm64 and all tools exist as shims."""
    bin_dir = tmp_path / "shim-bin"
    bin_dir.mkdir()
    _make_shim(
        bin_dir,
        "uname",
        'if [ "$1" = "-m" ]; then echo arm64; else echo Darwin; fi',
    )
    _make_shim(bin_dir, "brew", "echo brew-shim: should not run >&2; exit 1")
    _make_shim(bin_dir, "uv", "echo uv-shim: should not run >&2; exit 1")
    _make_shim(bin_dir, "ffmpeg", "exit 0")
    _make_shim(bin_dir, "xcode-select", "echo /Library/Developer/CommandLineTools")
    _make_shim(
        bin_dir, "live-transcriber", "echo live-transcriber-shim: should not run >&2; exit 1"
    )
    home = tmp_path / "home"
    home.mkdir()
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HOME"] = str(home)
    return env


def _run(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_script_exists_and_is_executable() -> None:
    assert SCRIPT.is_file()
    assert os.access(SCRIPT, os.X_OK)


def test_refuses_non_macos(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _make_shim(bin_dir, "uname", "echo Linux")
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    result = _run(["--dry-run"], env)
    assert result.returncode != 0
    assert "macOS" in result.stderr


def test_dry_run_happy_path_plans_core_install(shim_env: dict[str, str]) -> None:
    result = _run(["--dry-run"], shim_env)
    assert result.returncode == 0, result.stderr + result.stdout
    out = result.stdout
    assert "uv tool install" in out
    assert "live-transcriber doctor" in out
    # tools already present -> no brew installs planned
    assert "brew install" not in out
    # core install does not pull the heavy torch stack
    assert "whisperx" not in out
    # nothing actually executed
    assert "should not run" not in result.stderr


def test_dry_run_offline_adds_heavy_extras(shim_env: dict[str, str]) -> None:
    result = _run(["--dry-run", "--offline"], shim_env)
    assert result.returncode == 0, result.stderr + result.stdout
    out = result.stdout
    assert "whisperx" in out
    assert "diarization" in out
    # mlx extra is included; its wheel markers make it a no-op off Apple Silicon
    assert "mlx" in out


def test_dry_run_plans_brew_install_for_missing_ffmpeg(
    shim_env: dict[str, str], tmp_path: Path
) -> None:
    os.remove(Path(shim_env["PATH"].split(":", 1)[0]) / "ffmpeg")
    # a PATH without any real ffmpeg: keep only the shim dir + minimal system dirs
    result = _run(["--dry-run"], _without_tool(shim_env, "ffmpeg"))
    assert result.returncode == 0, result.stderr + result.stdout
    assert "brew install ffmpeg" in result.stdout


def _without_tool(env: dict[str, str], tool: str) -> dict[str, str]:
    """Return env whose PATH cannot resolve ``tool`` outside the shim dir."""
    shim_dir, rest = env["PATH"].split(":", 1)
    filtered = [d for d in rest.split(":") if not (Path(d) / tool).exists()]
    out = dict(env)
    out["PATH"] = ":".join([shim_dir, *filtered])
    return out


def test_requires_homebrew(shim_env: dict[str, str]) -> None:
    os.remove(Path(shim_env["PATH"].split(":", 1)[0]) / "brew")
    env = _without_tool(shim_env, "brew")
    result = _run(["--dry-run"], env)
    assert result.returncode != 0
    assert "brew.sh" in result.stderr


def test_rejects_unknown_flag(shim_env: dict[str, str]) -> None:
    result = _run(["--bogus"], shim_env)
    assert result.returncode != 0


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck not installed")
def test_shellcheck_clean() -> None:
    result = subprocess.run(
        ["shellcheck", str(SCRIPT)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_install_desktop_script_redirects_macos_users(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _make_shim(bin_dir, "uname", "echo Darwin")
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    result = subprocess.run(
        ["bash", str(REPO_ROOT / "packaging" / "install-desktop.sh")],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode != 0
    assert "install-macos.sh" in result.stderr
