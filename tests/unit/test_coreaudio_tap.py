from __future__ import annotations

import shutil
from pathlib import Path
from subprocess import CompletedProcess
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from live_meeting_transcriber.audio import coreaudio_tap
from live_meeting_transcriber.audio.capture import AudioCaptureError
from live_meeting_transcriber.audio.coreaudio_tap import (
    COREAUDIO_TAP_SOURCE,
    MacosAudioCapture,
)


class _FakeProc:
    def __init__(self) -> None:
        self.returncode = 0

    def communicate(self, timeout: float | None = None) -> tuple[bytes, bytes]:
        return (b"", b"rate=48000.0 ch=2 float=1")


def _install_fake_run(
    monkeypatch: pytest.MonkeyPatch, calls: list[list[str]], *, raw_bytes: bytes = b"\x00\x01" * 200
) -> None:
    def fake_run(cmd: list[str], **_kw: Any) -> CompletedProcess[str]:
        calls.append(cmd)
        name = str(cmd[0])
        if name.endswith("systemaudiotap"):
            out = cmd[cmd.index("--out") + 1]
            Path(out).write_bytes(raw_bytes)
        elif name == "ffmpeg":
            Path(cmd[-1]).write_bytes(b"RIFF____WAVE")
        return CompletedProcess(cmd, 0, "", "rate=48000.0 ch=2 float=1")

    monkeypatch.setattr(coreaudio_tap, "_run", fake_run)


# --- tap capture path -------------------------------------------------------


def test_tap_source_captures_via_helper_then_converts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []
    _install_fake_run(monkeypatch, calls)
    cap = MacosAudioCapture(helper_path=tmp_path / "systemaudiotap")

    chunk = cap.capture_chunk(
        session_id=uuid4(),
        source=COREAUDIO_TAP_SOURCE,
        microphone_source=None,
        chunk_seconds=5,
        sample_rate_hz=16000,
        channels=1,
        output_dir=tmp_path,
    )

    assert chunk.path.exists()
    assert chunk.sample_rate_hz == 16000
    # helper ran with the chunk duration
    helper_cmd = next(c for c in calls if str(c[0]).endswith("systemaudiotap"))
    assert "--seconds" in helper_cmd and "5" in helper_cmd
    # ffmpeg converted raw f32le -> 16k mono s16le WAV (no avfoundation/pulse capture involved)
    ffmpeg_cmd = next(c for c in calls if c[0] == "ffmpeg")
    joined = " ".join(ffmpeg_cmd)
    assert "f32le" in joined
    assert "pcm_s16le" in joined
    assert "16000" in joined
    assert "avfoundation" not in joined
    assert "pulse" not in joined
    # exact-length enforcement so quiet gaps don't shorten the chunk and drift the timeline
    assert "apad" in joined
    assert "-t" in ffmpeg_cmd and "5" in ffmpeg_cmd


def test_tap_silence_produces_padded_silent_wav(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []
    # empty raw file == pure silence during the chunk window
    _install_fake_run(monkeypatch, calls, raw_bytes=b"")
    cap = MacosAudioCapture(helper_path=tmp_path / "systemaudiotap")

    chunk = cap.capture_chunk(
        session_id=uuid4(),
        source=COREAUDIO_TAP_SOURCE,
        microphone_source=None,
        chunk_seconds=7,
        sample_rate_hz=16000,
        channels=1,
        output_dir=tmp_path,
    )

    assert chunk.path.exists()
    ffmpeg_cmd = next(c for c in calls if c[0] == "ffmpeg")
    joined = " ".join(ffmpeg_cmd)
    # a silent chunk of the right duration keeps the recorder timeline aligned
    assert "anullsrc" in joined
    assert "7" in ffmpeg_cmd


def test_non_tap_source_delegates_to_avfoundation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []
    _install_fake_run(monkeypatch, calls)
    avf = MagicMock()
    avf.capture_chunk.return_value = "delegated"
    cap = MacosAudioCapture(avfoundation=avf, helper_path=tmp_path / "systemaudiotap")

    result = cap.capture_chunk(
        session_id=uuid4(),
        source=":3",
        microphone_source=None,
        chunk_seconds=5,
        sample_rate_hz=16000,
        channels=1,
        output_dir=tmp_path,
    )

    assert result is avf.capture_chunk.return_value
    avf.capture_chunk.assert_called_once()
    # tap helper must not run for a normal avfoundation/BlackHole device
    assert not any(str(c[0]).endswith("systemaudiotap") for c in calls)


def test_tap_with_microphone_mixes_via_amix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_calls: list[list[str]] = []
    popen_calls: list[list[str]] = []

    def fake_popen(cmd: list[str], **_kw: Any) -> _FakeProc:
        popen_calls.append(cmd)
        name = str(cmd[0])
        if name.endswith("systemaudiotap"):
            Path(cmd[cmd.index("--out") + 1]).write_bytes(b"\x00\x01" * 200)
        elif name == "ffmpeg":
            Path(cmd[-1]).write_bytes(b"RIFF____WAVE")
        return _FakeProc()

    def fake_run(cmd: list[str], **_kw: Any) -> CompletedProcess[str]:
        run_calls.append(cmd)
        if cmd[0] == "ffmpeg":
            Path(cmd[-1]).write_bytes(b"RIFF____WAVE")
        return CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(coreaudio_tap, "_popen", fake_popen)
    monkeypatch.setattr(coreaudio_tap, "_run", fake_run)
    cap = MacosAudioCapture(helper_path=tmp_path / "systemaudiotap")

    cap.capture_chunk(
        session_id=uuid4(),
        source=COREAUDIO_TAP_SOURCE,
        microphone_source=":2",
        chunk_seconds=5,
        sample_rate_hz=16000,
        channels=1,
        output_dir=tmp_path,
    )

    # tap + mic captured concurrently (both started before the combine step)
    assert any(str(c[0]).endswith("systemaudiotap") for c in popen_calls)
    assert any(c[0] == "ffmpeg" and "avfoundation" in " ".join(c) for c in popen_calls)
    combine = next(c for c in run_calls if c[0] == "ffmpeg")
    assert "amix" in " ".join(combine)


# --- helper build -----------------------------------------------------------


def test_build_helper_raises_without_swiftc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _n: None)
    with pytest.raises(AudioCaptureError, match="swiftc"):
        coreaudio_tap.build_helper(cache_dir=tmp_path)


def test_build_helper_compiles_and_adhoc_signs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(shutil, "which", lambda n: f"/usr/bin/{n}")
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_kw: Any) -> CompletedProcess[str]:
        calls.append(cmd)
        if cmd[0] == "swiftc":
            Path(cmd[cmd.index("-o") + 1]).write_bytes(b"\x7fELF-ish")
        return CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(coreaudio_tap, "_run", fake_run)

    binary = coreaudio_tap.build_helper(cache_dir=tmp_path)

    assert binary.exists()
    swiftc = next(c for c in calls if c[0] == "swiftc")
    joined = " ".join(swiftc)
    assert "systemaudiotap.swift" in joined
    assert "__info_plist" in joined  # embeds Info.plist so the TCC prompt fires
    codesign = next(c for c in calls if c[0] == "codesign")
    assert "-" in codesign  # ad-hoc identity


def test_build_helper_reuses_fresh_binary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda n: f"/usr/bin/{n}")
    binary = tmp_path / "systemaudiotap"
    binary.write_bytes(b"built")
    # make it newer than the sources
    import os
    import time

    future = time.time() + 10_000
    os.utime(binary, (future, future))
    called = False

    def fake_run(cmd: list[str], **_kw: Any) -> CompletedProcess[str]:
        nonlocal called
        called = True
        return CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(coreaudio_tap, "_run", fake_run)

    result = coreaudio_tap.build_helper(cache_dir=tmp_path)

    assert result == binary
    assert called is False  # no rebuild when the cached binary is newer than sources
