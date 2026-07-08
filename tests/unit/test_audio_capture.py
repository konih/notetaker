from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch
from uuid import uuid4

from live_meeting_transcriber.audio.capture import FfmpegPulseAudioCapture
from live_meeting_transcriber.utils.time import utc_now


def _fake_run(cmd: list[str], **_kwargs: object) -> CompletedProcess[str]:
    return CompletedProcess(cmd, 0, "", "")


def test_capture_chunk_single_input_builds_ffmpeg_without_amix(tmp_path: Path) -> None:
    cap = FfmpegPulseAudioCapture()
    with patch(
        "live_meeting_transcriber.audio.capture.subprocess.run", side_effect=_fake_run
    ) as run:
        cap.capture_chunk(
            session_id=uuid4(),
            source="sink.monitor",
            microphone_source=None,
            chunk_seconds=5,
            sample_rate_hz=16000,
            channels=1,
            output_dir=tmp_path,
        )
    cmd = run.call_args[0][0]
    assert cmd[0] == "ffmpeg"
    assert cmd.count("-i") == 1
    assert "amix" not in " ".join(cmd)


def test_capture_chunk_with_microphone_uses_amix(tmp_path: Path) -> None:
    cap = FfmpegPulseAudioCapture()
    with patch(
        "live_meeting_transcriber.audio.capture.subprocess.run", side_effect=_fake_run
    ) as run:
        cap.capture_chunk(
            session_id=uuid4(),
            source="sink.monitor",
            microphone_source="alsa_input.mic",
            chunk_seconds=5,
            sample_rate_hz=16000,
            channels=1,
            output_dir=tmp_path,
        )
    cmd = run.call_args[0][0]
    joined = " ".join(cmd)
    assert cmd.count("-i") == 2
    assert "amix" in joined
    assert "aresample=async=1" in joined
    assert "alsa_input.mic" in cmd


def test_capture_chunk_stereo_with_microphone_uses_join(tmp_path: Path) -> None:
    cap = FfmpegPulseAudioCapture()
    with patch(
        "live_meeting_transcriber.audio.capture.subprocess.run", side_effect=_fake_run
    ) as run:
        cap.capture_chunk(
            session_id=uuid4(),
            source="sink.monitor",
            microphone_source="alsa_input.mic",
            chunk_seconds=5,
            sample_rate_hz=16000,
            channels=2,
            output_dir=tmp_path,
        )
    cmd = run.call_args[0][0]
    joined = " ".join(cmd)
    assert cmd.count("-i") == 2
    assert "join=inputs=2:channel_layout=stereo" in joined
    assert "alsa_input.mic" in cmd


def test_capture_chunk_timestamps_are_timezone_aware(tmp_path: Path) -> None:
    cap = FfmpegPulseAudioCapture()
    with patch("live_meeting_transcriber.audio.capture.subprocess.run", side_effect=_fake_run):
        chunk = cap.capture_chunk(
            session_id=uuid4(),
            source="sink.monitor",
            microphone_source=None,
            chunk_seconds=5,
            sample_rate_hz=16000,
            channels=1,
            output_dir=tmp_path,
        )
    # Timestamps must be tz-aware so timedelta math and comparisons against
    # utc_now() (done in the transcriber/diarizer) don't raise TypeError.
    assert chunk.started_at.tzinfo is not None
    assert chunk.ended_at.tzinfo is not None
    # A naive started_at would raise "can't compare offset-naive and offset-aware".
    assert chunk.started_at + timedelta(seconds=1) <= utc_now() + timedelta(days=1)


def test_capture_chunk_skips_duplicate_when_mic_equals_monitor(tmp_path: Path) -> None:
    cap = FfmpegPulseAudioCapture()
    with patch(
        "live_meeting_transcriber.audio.capture.subprocess.run", side_effect=_fake_run
    ) as run:
        cap.capture_chunk(
            session_id=uuid4(),
            source="same",
            microphone_source="same",
            chunk_seconds=5,
            sample_rate_hz=16000,
            channels=1,
            output_dir=tmp_path,
        )
    cmd = run.call_args[0][0]
    assert cmd.count("-i") == 1
