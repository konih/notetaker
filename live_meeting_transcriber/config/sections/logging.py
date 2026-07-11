"""Logging settings: level, rotating file sink, and its resolved location."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings

from live_meeting_transcriber.config.paths import default_data_dir


class LoggingSettings(BaseSettings):
    """Application log level and rotating JSON-lines file sink."""

    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_enable_file: bool = Field(default=True, alias="LOG_ENABLE_FILE")
    log_file: Path | None = Field(default=None, alias="LOG_FILE")
    log_file_max_mb: int = Field(default=10, alias="LOG_FILE_MAX_MB", ge=1, le=512)
    log_file_backup_count: int = Field(default=5, alias="LOG_FILE_BACKUP_COUNT", ge=0, le=50)

    @field_validator("log_level", mode="before")
    @classmethod
    def _strip_log_level(cls, v: object) -> str:
        if v is None:
            return "INFO"
        s = str(v).strip()
        return s if s else "INFO"

    def resolved_log_file(self) -> Path:
        """Absolute path for the rotating application log (JSON lines)."""
        if self.log_file is not None:
            return Path(self.log_file).expanduser().resolve()
        data_dir = default_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        return (data_dir / "logs" / "live-meeting-transcriber.log").resolve()

    @property
    def log_file_max_bytes(self) -> int:
        return int(self.log_file_max_mb) * 1024 * 1024
