"""Offline finalize settings: WhisperX transcription/alignment after a session."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class WhisperXSettings(BaseSettings):
    """Full-session WhisperX pass (optional extra ``whisperx``; see ``finalize``)."""

    # After full-session WhisperX pass (see ``live-transcriber finalize``).
    finalize_on_session_stop: bool = Field(default=False, alias="FINALIZE_ON_SESSION_STOP")

    # F12: engine for the offline finalize transcription. ``auto`` uses mlx-whisper on
    # the Apple GPU when running on Apple Silicon with the ``mlx`` extra installed
    # (installing the extra is the opt-in; F11 spike: ~7x faster than cpu/int8), else
    # WhisperX/CTranslate2. Explicit values win; an explicit ``mlx`` that cannot run on
    # this machine degrades to the WhisperX path with a logged warning (never an error).
    offline_asr_engine: Literal["auto", "whisperx", "mlx"] = Field(
        default="auto", alias="OFFLINE_ASR_ENGINE"
    )
    # Hugging Face repo of the MLX-converted Whisper checkpoint (~1.6 GB, downloaded on
    # first use like the WhisperX models).
    mlx_whisper_model: str = Field(
        default="mlx-community/whisper-large-v3-turbo", alias="MLX_WHISPER_MODEL"
    )
    # Hallucination-on-silence gate for the MLX engine: drop transcript segments whose
    # audio window's RMS is strictly below this (mlx-whisper lacks the baseline's external
    # VAD suppression; F11 saw a "Thank you." invented over a quiet stretch). -60 dBFS is
    # far below quiet speech (~-40) so real speech is never gated; unmeasurable windows
    # keep the segment (fail open). Set -120 to effectively disable.
    mlx_silence_gate_dbfs: float = Field(
        default=-60.0, alias="MLX_SILENCE_GATE_DBFS", ge=-120.0, le=0.0
    )

    whisperx_model: str = Field(default="large-v3-turbo", alias="WHISPERX_MODEL")
    whisperx_device: str | None = Field(default=None, alias="WHISPERX_DEVICE")
    whisperx_torch_device: str | None = Field(default=None, alias="WHISPERX_TORCH_DEVICE")
    whisperx_compute_type: str = Field(default="float16", alias="WHISPERX_COMPUTE_TYPE")
    # Lower values reduce VRAM during transcribe (OOM: try 2-4 and/or a smaller WHISPERX_MODEL).
    whisperx_batch_size: int = Field(default=8, alias="WHISPERX_BATCH_SIZE", ge=1, le=64)
    whisperx_language: str | None = Field(default=None, alias="WHISPERX_LANGUAGE")
    whisperx_skip_alignment: bool = Field(default=False, alias="WHISPERX_SKIP_ALIGNMENT")
    # When unset: on Apple Silicon with usable MPS, pyannote auto-runs on ``mps`` (F11 spike:
    # byte-identical output, ~8-20x faster; auto-falls back to CPU if MPS errors at runtime).
    # If alignment uses CUDA, pyannote defaults to CPU (avoids OOM from a second GPU model after
    # Whisper). Explicit values always win — set ``cpu`` to opt out, ``cuda``/``cuda:0`` for VRAM.
    whisperx_diarize_device: str | None = Field(default=None, alias="WHISPERX_DIARIZE_DEVICE")

    @field_validator(
        "whisperx_device", "whisperx_torch_device", "whisperx_diarize_device", mode="before"
    )
    @classmethod
    def _optional_whisperx_device_str(cls, v: object) -> str | None:
        if v is None or v == "":
            return None
        s = str(v).strip()
        return s if s else None
