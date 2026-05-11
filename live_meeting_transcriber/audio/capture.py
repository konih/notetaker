from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

from live_meeting_transcriber.domain.models import AudioChunk


class AudioCaptureError(RuntimeError):
    pass


class FfmpegPulseAudioCapture:
    """
    Captures audio from PipeWire/PulseAudio sources using ffmpeg.

    This is Linux-first and intentionally avoids in-process audio backends, which
    tend to be brittle across desktop configurations.
    """

    def capture_chunk(
        self,
        *,
        session_id: UUID,
        source: str,
        chunk_seconds: int,
        sample_rate_hz: int,
        channels: int,
        output_dir: Path,
    ) -> AudioChunk:
        output_dir.mkdir(parents=True, exist_ok=True)

        chunk_id = uuid4()
        started_at = datetime.utcnow()
        out_path = output_dir / f"{chunk_id}.wav"
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "pulse",
            "-i",
            source,
            "-t",
            str(chunk_seconds),
            "-ac",
            str(channels),
            "-ar",
            str(sample_rate_hz),
            "-acodec",
            "pcm_s16le",
            str(out_path),
        ]

        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except FileNotFoundError as e:
            raise AudioCaptureError("ffmpeg not found; install ffmpeg") from e
        except subprocess.CalledProcessError as e:
            raise AudioCaptureError(f"ffmpeg failed: {e.stderr.strip()}") from e

        ended_at = datetime.utcnow()
        return AudioChunk(
            id=chunk_id,
            session_id=session_id,
            started_at=started_at,
            ended_at=ended_at,
            path=out_path,
            sample_rate_hz=sample_rate_hz,
            channels=channels,
        )

