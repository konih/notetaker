"""A3 robustness batch: failures surface as logged/diagnosable errors, not silent
``pass`` or ``AttributeError`` on malformed external-tool output.

Covers ARCH-06 (container.close), ARCH-07 (cli record session-end), ARCH-08 (stereo
WAV-read fallback logging) and ARCH-13 (``e.stderr`` may be ``None``).
"""

from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest
from live_meeting_transcriber.application.container import Container
from live_meeting_transcriber.audio import stereo
from live_meeting_transcriber.audio.capture import AudioCaptureError, FfmpegPulseAudioCapture
from live_meeting_transcriber.audio.devices import AudioDeviceError, PactlAudioDeviceProvider
from live_meeting_transcriber.audio.wav_segment import (
    WavSegmentExtractionError,
    extract_wav_time_range,
)
from live_meeting_transcriber.cli.main import _end_session_safely
from structlog.testing import capture_logs


def _called_process_error_none_stderr(cmd: list[str]) -> subprocess.CalledProcessError:
    """A CalledProcessError whose ``stderr`` is ``None`` (as when ``text`` output is absent)."""
    return subprocess.CalledProcessError(returncode=1, cmd=cmd, output=None, stderr=None)


# --- ARCH-06: Container.close() logs before swallowing --------------------------------


def test_container_close_logs_when_connection_close_raises() -> None:
    conn = Mock()
    conn.close.side_effect = RuntimeError("db is busy")
    container = object.__new__(Container)
    object.__setattr__(container, "_conn", conn)

    with capture_logs() as logs:
        container.close()  # must not propagate

    events = [e for e in logs if e.get("log_level") in {"warning", "error"}]
    assert events, "expected a logged warning/error when connection close fails"
    assert any("close" in str(e.get("event", "")) for e in events)


# --- ARCH-07: cli record session-end failure is logged and surfaced -------------------


def test_end_session_safely_logs_and_warns_on_failure(capsys: pytest.CaptureFixture[str]) -> None:
    sessions = Mock()
    sessions.end.side_effect = RuntimeError("db gone")
    log = Mock()
    session_id = uuid4()

    _end_session_safely(sessions, session_id, log=log)

    log.warning.assert_called_once()
    assert log.warning.call_args.args[0] == "session_end_failed"
    # A failed end must NOT be reported as a clean "session_ended".
    assert not any(c.args and c.args[0] == "session_ended" for c in log.info.call_args_list)
    err = capsys.readouterr().err
    assert "session" in err.lower() and "warn" in err.lower()


def test_end_session_safely_success_logs_ended(capsys: pytest.CaptureFixture[str]) -> None:
    sessions = Mock()
    log = Mock()
    session_id = uuid4()

    _end_session_safely(sessions, session_id, log=log)

    sessions.end.assert_called_once_with(session_id)
    assert log.info.call_args.args[0] == "session_ended"
    log.warning.assert_not_called()
    assert capsys.readouterr().err == ""


# --- ARCH-08: stereo WAV-read failures are logged before the fallback -----------------


def test_read_stereo_pcm_logs_on_corrupt_wav(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # numpy is an optional extra absent from the base test env; the WAV-read path is
    # only reached once ``import numpy`` succeeds, so make it importable (unused here).
    monkeypatch.setitem(sys.modules, "numpy", types.ModuleType("numpy"))
    bad = tmp_path / "not-a-wav.wav"
    bad.write_bytes(b"this is not a wav file")

    with capture_logs() as logs:
        result = stereo.read_stereo_pcm(bad)

    assert result is None
    assert any(e.get("log_level") in {"warning", "error"} for e in logs), (
        "corrupt WAV read should be logged, not silently swallowed"
    )


def test_rms_mixdown_logs_before_ffmpeg_fallback(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setitem(sys.modules, "numpy", types.ModuleType("numpy"))
    bad = tmp_path / "not-a-wav.wav"
    bad.write_bytes(b"nonsense")
    sentinel = tmp_path / "mono.wav"
    fallback = Mock(return_value=sentinel)
    monkeypatch.setattr(stereo, "_ffmpeg_average_mono", fallback)

    with capture_logs() as logs:
        out = stereo.rms_mixdown_to_mono_wav(bad, sample_rate_hz=16000)

    assert out == sentinel
    fallback.assert_called_once()
    assert any(e.get("log_level") in {"warning", "error"} for e in logs), (
        "falling back to ffmpeg should log the original read error"
    )


# --- ARCH-13: e.stderr may be None; error must render without AttributeError -----------


def test_wav_segment_extract_handles_none_stderr(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def boom(cmd: list[str], **_kwargs: object) -> object:
        raise _called_process_error_none_stderr(cmd)

    monkeypatch.setattr("live_meeting_transcriber.audio.wav_segment.subprocess.run", boom)

    with pytest.raises(WavSegmentExtractionError):
        extract_wav_time_range(
            src=tmp_path / "in.wav",
            dest=tmp_path / "out.wav",
            start_seconds=0.0,
            end_seconds=1.0,
            sample_rate_hz=16000,
            channels=1,
        )


def test_pactl_list_sources_handles_none_stderr(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def boom(cmd: list[str], **_kwargs: object) -> object:
        raise _called_process_error_none_stderr(cmd)

    monkeypatch.setattr("live_meeting_transcriber.audio.devices.subprocess.run", boom)

    with pytest.raises(AudioDeviceError):
        PactlAudioDeviceProvider().list_sources()


def test_capture_chunk_handles_none_stderr(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def boom(cmd: list[str], **_kwargs: object) -> object:
        raise _called_process_error_none_stderr(cmd)

    monkeypatch.setattr("live_meeting_transcriber.audio.capture.subprocess.run", boom)

    with pytest.raises(AudioCaptureError):
        FfmpegPulseAudioCapture().capture_chunk(
            session_id=uuid4(),
            source="sink.monitor",
            microphone_source=None,
            chunk_seconds=5,
            sample_rate_hz=16000,
            channels=1,
            output_dir=tmp_path,
        )
