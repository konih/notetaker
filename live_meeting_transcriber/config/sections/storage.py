"""Storage settings: SQLite database location and the default data directory."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings

from live_meeting_transcriber.config.paths import default_data_dir, default_database_url


class StorageSettings(BaseSettings):
    """Where transcripts, summaries, and session metadata persist."""

    database_url: str = Field(
        default_factory=default_database_url,
        alias="DATABASE_URL",
    )

    def ensure_data_dir(self) -> Path:
        # Only used for default sqlite paths; callers should not rely on implicit globals.
        default_dir = default_data_dir()
        default_dir.mkdir(parents=True, exist_ok=True)
        return default_dir
