from __future__ import annotations

from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch
from uuid import uuid4

from live_meeting_transcriber.audio.capture import FfmpegAvfoundationCapture


def _fake_run(cmd: list[str], **_kwargs: object) -> CompletedProcess[str]:
    return CompletedProcess(cmd, 0, "", "")


def test_avfoundation_capture_single_input(tmp_path: Path) -> None:
    cap = FfmpegAvfoundationCapture()
    with patch(
        "live_meeting_transcriber.audio.capture.subprocess.run", side_effect=_fake_run
    ) as run:
        cap.capture_chunk(
            session_id=uuid4(),
            source=":3",
            microphone_source=None,
            chunk_seconds=5,
            sample_rate_hz=16000,
            channels=1,
            output_dir=tmp_path,
        )
    cmd = run.call_args[0][0]
    assert "-f" in cmd
    assert "avfoundation" in cmd
    assert ":3" in cmd
    assert "pulse" not in cmd


def test_avfoundation_capture_with_microphone_uses_amix(tmp_path: Path) -> None:
    cap = FfmpegAvfoundationCapture()
    with patch(
        "live_meeting_transcriber.audio.capture.subprocess.run", side_effect=_fake_run
    ) as run:
        cap.capture_chunk(
            session_id=uuid4(),
            source=":5",
            microphone_source=":3",
            chunk_seconds=5,
            sample_rate_hz=16000,
            channels=1,
            output_dir=tmp_path,
        )
    cmd = run.call_args[0][0]
    joined = " ".join(cmd)
    assert cmd.count("-i") == 2
    assert "amix" in joined
    assert ":5" in cmd
    assert ":3" in cmd
