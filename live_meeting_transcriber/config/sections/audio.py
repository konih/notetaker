"""Audio capture settings: chunking, sample format, mic mix, and silence skipping."""

from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings


class AudioSettings(BaseSettings):
    """Live-capture knobs for the chunked recorder."""

    audio_chunk_seconds: int = Field(default=10, alias="AUDIO_CHUNK_SECONDS", ge=1, le=300)
    audio_sample_rate: int = Field(default=16000, alias="AUDIO_SAMPLE_RATE", ge=8000, le=48000)
    audio_channels: int = Field(default=1, alias="AUDIO_CHANNELS", ge=1, le=2)
    # When AUDIO_CHANNELS=2 and mic+monitor capture: ``mixdown`` = RMS mono for live ASR;
    # ``dual_path`` = transcribe L (mic) and R (system) separately (faster-whisper only).
    audio_stereo_mode: Literal["mixdown", "dual_path"] = Field(
        default="mixdown", alias="AUDIO_STEREO_MODE"
    )
    keep_audio_chunks: bool = Field(default=False, alias="KEEP_AUDIO_CHUNKS")
    # Silence skipping (F1): don't send near-silent chunks to the transcriber. The
    # default threshold is deliberately far below quiet speech (~-40 dBFS RMS) so only
    # true digital near-silence is skipped; audio always lands in full_session.wav.
    audio_silence_skip_enabled: bool = Field(default=True, alias="AUDIO_SILENCE_SKIP_ENABLED")
    audio_silence_threshold_dbfs: float = Field(
        default=-70.0, alias="AUDIO_SILENCE_THRESHOLD_DBFS", ge=-120.0, le=0.0
    )
    audio_include_microphone: bool = Field(default=True, alias="AUDIO_INCLUDE_MICROPHONE")
    audio_microphone_source: str | None = Field(default=None, alias="AUDIO_MICROPHONE_SOURCE")
    # macOS system-audio capture strategy. ``auto`` (default) uses the driver-free Core Audio
    # tap on macOS 14.4+ and otherwise falls back to an avfoundation loopback device
    # (BlackHole/Loopback). ``coreaudio_tap`` forces the native tap; ``avfoundation`` forces the
    # BlackHole/loopback device path. Ignored on Linux.
    audio_macos_system_capture: Literal["auto", "coreaudio_tap", "avfoundation"] = Field(
        default="auto", alias="AUDIO_MACOS_SYSTEM_CAPTURE"
    )
