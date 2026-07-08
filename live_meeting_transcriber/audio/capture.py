from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from live_meeting_transcriber.domain.models import AudioChunk
from live_meeting_transcriber.utils.time import utc_now

AudioBackend = Literal["pulse", "avfoundation"]


class AudioCaptureError(RuntimeError):
    pass


class FfmpegAudioCapture:
    """
    Captures audio using ffmpeg.

    Linux uses PipeWire/PulseAudio (``-f pulse``). macOS uses AVFoundation
    (``-f avfoundation``) with device specs like ``:3`` from ``live-transcriber devices``.

    When ``microphone_source`` is set (and distinct from ``source``), records
    system/monitor and microphone together via ``amix`` (mono) or ``join`` (stereo).
    """

    def __init__(self, *, backend: AudioBackend = "pulse") -> None:
        self._backend = backend

    def _input_prefix(self, source: str) -> list[str]:
        if self._backend == "avfoundation":
            return [
                "-f",
                "avfoundation",
                "-thread_queue_size",
                "4096",
                "-i",
                source,
            ]
        return ["-f", "pulse", "-i", source]

    def capture_chunk(
        self,
        *,
        session_id: UUID,
        source: str,
        microphone_source: str | None = None,
        chunk_seconds: int,
        sample_rate_hz: int,
        channels: int,
        output_dir: Path,
    ) -> AudioChunk:
        output_dir.mkdir(parents=True, exist_ok=True)

        chunk_id = uuid4()
        started_at = utc_now()
        out_path = output_dir / f"{chunk_id}.wav"

        mic = microphone_source if microphone_source and microphone_source != source else None

        if mic is None:
            cmd: list[str] = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                *self._input_prefix(source),
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
        elif channels >= 2:
            # Stereo: left = microphone (local), right = monitor/system (remote), for offline
            # YOU/REMOTE mapping and optional dual-path live transcription.
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                *self._input_prefix(source),
                *self._input_prefix(mic),
                "-filter_complex",
                "[0:a]aresample=async=1,pan=mono|c0=c0[sys];"
                "[1:a]aresample=async=1,pan=mono|c0=c0[mic];"
                "[mic][sys]join=inputs=2:channel_layout=stereo[aout]",
                "-map",
                "[aout]",
                "-t",
                str(chunk_seconds),
                "-ar",
                str(sample_rate_hz),
                "-acodec",
                "pcm_s16le",
                str(out_path),
            ]
        else:
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                *self._input_prefix(source),
                *self._input_prefix(mic),
                "-filter_complex",
                # aresample async=1 reduces drift when one source is idle while the other
                # is active (common monitor+mic amix issue: mic appears only when system audio plays).
                "[0:a]aresample=async=1[a0];[1:a]aresample=async=1[a1];"
                "[a0][a1]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0[aout]",
                "-map",
                "[aout]",
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
            raise AudioCaptureError(f"ffmpeg failed: {(e.stderr or '').strip()}") from e

        ended_at = utc_now()
        return AudioChunk(
            id=chunk_id,
            session_id=session_id,
            started_at=started_at,
            ended_at=ended_at,
            path=out_path,
            sample_rate_hz=sample_rate_hz,
            channels=channels,
        )


class FfmpegPulseAudioCapture(FfmpegAudioCapture):
    """Linux PipeWire/PulseAudio capture (backwards-compatible alias)."""

    def __init__(self) -> None:
        super().__init__(backend="pulse")


class FfmpegAvfoundationCapture(FfmpegAudioCapture):
    """macOS AVFoundation capture."""

    def __init__(self) -> None:
        super().__init__(backend="avfoundation")
