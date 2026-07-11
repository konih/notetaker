"""Provider settings: transcription/LLM provider selection and model knobs."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class ProviderSettings(BaseSettings):
    """Cloud (OpenAI) and local (faster-whisper) provider configuration."""

    transcription_provider: Literal["openai", "faster_whisper"] = Field(
        default="openai", alias="TRANSCRIPTION_PROVIDER"
    )
    llm_provider: Literal["openai"] = Field(default="openai", alias="LLM_PROVIDER")

    # OpenAI
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    transcription_model: str = Field(default="gpt-4o-mini-transcribe", alias="TRANSCRIPTION_MODEL")
    summary_model: str = Field(default="gpt-4o-mini", alias="SUMMARY_MODEL")

    # faster-whisper (local transcription; optional extra `faster-whisper`)
    faster_whisper_model: str = Field(default="small", alias="FASTER_WHISPER_MODEL")
    faster_whisper_device: str = Field(default="auto", alias="FASTER_WHISPER_DEVICE")
    faster_whisper_compute_type: str = Field(default="default", alias="FASTER_WHISPER_COMPUTE_TYPE")
    faster_whisper_language: str | None = Field(default=None, alias="FASTER_WHISPER_LANGUAGE")

    @field_validator("faster_whisper_language", mode="before")
    @classmethod
    def _faster_whisper_language(cls, v: object) -> str | None:
        if v is None or v == "":
            return None
        return str(v).strip() or None

    def effective_transcription_model_display(self) -> str:
        """Model name shown in UI / logs (OpenAI model id vs Whisper size)."""
        if self.transcription_provider == "faster_whisper":
            return self.faster_whisper_model
        return self.transcription_model
