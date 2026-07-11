"""Offline finalize settings: WhisperX transcription/alignment after a session."""

from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class WhisperXSettings(BaseSettings):
    """Full-session WhisperX pass (optional extra ``whisperx``; see ``finalize``)."""

    # After full-session WhisperX pass (see ``live-transcriber finalize``).
    finalize_on_session_stop: bool = Field(default=False, alias="FINALIZE_ON_SESSION_STOP")

    whisperx_model: str = Field(default="large-v3-turbo", alias="WHISPERX_MODEL")
    whisperx_device: str | None = Field(default=None, alias="WHISPERX_DEVICE")
    whisperx_torch_device: str | None = Field(default=None, alias="WHISPERX_TORCH_DEVICE")
    whisperx_compute_type: str = Field(default="float16", alias="WHISPERX_COMPUTE_TYPE")
    # Lower values reduce VRAM during transcribe (OOM: try 2-4 and/or a smaller WHISPERX_MODEL).
    whisperx_batch_size: int = Field(default=8, alias="WHISPERX_BATCH_SIZE", ge=1, le=64)
    whisperx_language: str | None = Field(default=None, alias="WHISPERX_LANGUAGE")
    whisperx_skip_alignment: bool = Field(default=False, alias="WHISPERX_SKIP_ALIGNMENT")
    # When unset: if alignment uses CUDA/MPS, pyannote defaults to CPU (avoids OOM from a second
    # GPU model after Whisper). Set to ``cuda`` / ``cuda:0`` to force GPU diarization if you have VRAM.
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
