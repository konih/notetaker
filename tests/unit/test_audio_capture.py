from __future__ import annotations

from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch
from uuid import uuid4

from live_meeting_transcriber.audio.capture import FfmpegPulseAudioCapture


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
