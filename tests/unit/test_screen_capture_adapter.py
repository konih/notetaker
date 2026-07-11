"""F6 — macOS ``screencapture`` CLI adapter.

The adapter is hermetic-testable: binary discovery (``which``), the subprocess
runner, and the platform are injected, so no test touches the real screen, the
real binary, or macOS-only behavior (unit CI runs on Linux).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from live_meeting_transcriber.screencap.cli import ScreencaptureCli


def _which_found(name: str) -> str | None:
    return f"/usr/sbin/{name}"


def _which_missing(name: str) -> str | None:
    return None


def test_unavailable_on_non_macos() -> None:
    cap = ScreencaptureCli(which=_which_found, platform="linux")
    ok, reason = cap.availability()
    assert ok is False
    assert reason is not None and "macOS" in reason


def test_unavailable_when_binary_missing() -> None:
    cap = ScreencaptureCli(which=_which_missing, platform="darwin")
    ok, reason = cap.availability()
    assert ok is False
    assert reason is not None and "screencapture" in reason


def test_available_on_darwin_with_binary() -> None:
    cap = ScreencaptureCli(which=_which_found, platform="darwin")
    assert cap.availability() == (True, None)


def test_capture_returns_false_without_invoking_runner_when_unavailable(tmp_path: Path) -> None:
    calls: list[Sequence[str]] = []

    def runner(cmd: Sequence[str]) -> int:
        calls.append(cmd)
        return 0

    cap = ScreencaptureCli(which=_which_missing, platform="darwin", runner=runner)
    assert cap.capture(tmp_path / "shot.png") is False
    assert calls == []


def test_capture_returns_false_on_nonzero_exit(tmp_path: Path) -> None:
    cap = ScreencaptureCli(which=_which_found, platform="darwin", runner=lambda cmd: 1)
    assert cap.capture(tmp_path / "shot.png") is False


def test_capture_returns_false_when_no_file_written(tmp_path: Path) -> None:
    # e.g. screencapture exited 0 but produced nothing (seen with odd TCC states).
    cap = ScreencaptureCli(which=_which_found, platform="darwin", runner=lambda cmd: 0)
    assert cap.capture(tmp_path / "shot.png") is False


def test_capture_success_writes_png_silently(tmp_path: Path) -> None:
    out = tmp_path / "shot.png"
    seen: list[list[str]] = []

    def runner(cmd: Sequence[str]) -> int:
        seen.append(list(cmd))
        out.write_bytes(b"\x89PNG fake")
        return 0

    cap = ScreencaptureCli(which=_which_found, platform="darwin", runner=runner)
    assert cap.capture(out) is True
    (cmd,) = seen
    assert cmd[0] == "/usr/sbin/screencapture"  # resolved via which
    assert "-x" in cmd  # no shutter sound during a meeting
    assert str(out) == cmd[-1]
