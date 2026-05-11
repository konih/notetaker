from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Providers
    transcription_provider: Literal["openai"] = Field(default="openai", alias="TRANSCRIPTION_PROVIDER")
    llm_provider: Literal["openai"] = Field(default="openai", alias="LLM_PROVIDER")

    # OpenAI
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    transcription_model: str = Field(default="gpt-4o-mini-transcribe", alias="TRANSCRIPTION_MODEL")
    summary_model: str = Field(default="gpt-4o-mini", alias="SUMMARY_MODEL")

    # Storage
    database_url: str = Field(
        default="sqlite:////home/you/.local/share/live-meeting-transcriber/app.db",
        alias="DATABASE_URL",
    )

    # Audio
    audio_chunk_seconds: int = Field(default=10, alias="AUDIO_CHUNK_SECONDS", ge=1, le=300)
    audio_sample_rate: int = Field(default=16000, alias="AUDIO_SAMPLE_RATE", ge=8000, le=48000)
    audio_channels: int = Field(default=1, alias="AUDIO_CHANNELS", ge=1, le=2)
    keep_audio_chunks: bool = Field(default=False, alias="KEEP_AUDIO_CHUNKS")

    # Logging
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_enable_file: bool = Field(default=True, alias="LOG_ENABLE_FILE")
    log_file: Path | None = Field(default=None, alias="LOG_FILE")
    log_file_max_mb: int = Field(default=10, alias="LOG_FILE_MAX_MB", ge=1, le=512)
    log_file_backup_count: int = Field(default=5, alias="LOG_FILE_BACKUP_COUNT", ge=0, le=50)

    # Diarization (UI + future providers)
    diarization_enabled: bool = Field(default=False, alias="DIARIZATION_ENABLED")
    diarization_provider: str = Field(default="noop", alias="DIARIZATION_PROVIDER")

    def ensure_data_dir(self) -> Path:
        # Only used for default sqlite paths; callers should not rely on implicit globals.
        default_dir = Path.home() / ".local" / "share" / "live-meeting-transcriber"
        default_dir.mkdir(parents=True, exist_ok=True)
        return default_dir

    def resolved_log_file(self) -> Path:
        """Absolute path for the rotating application log (JSON lines)."""
        if self.log_file is not None:
            return Path(self.log_file).expanduser().resolve()
        return (self.ensure_data_dir() / "logs" / "live-meeting-transcriber.log").resolve()

    @property
    def log_file_max_bytes(self) -> int:
        return int(self.log_file_max_mb) * 1024 * 1024


def load_settings() -> Settings:
    return Settings()
