from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from live_meeting_transcriber.domain.models import SlideDetectionParams

APP_CONFIG_DIR_NAME = "live-meeting-transcriber"


def xdg_config_home() -> Path:
    """XDG base directory for user-specific configuration (``$XDG_CONFIG_HOME`` or ``~/.config``)."""
    raw = os.environ.get("XDG_CONFIG_HOME")
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / ".config").resolve()


def app_config_dir() -> Path:
    return xdg_config_home() / APP_CONFIG_DIR_NAME


def discover_env_file_paths() -> tuple[Path, ...]:
    """Existing ``.env`` files: XDG config dir first, then CWD (later entries override)."""
    candidates = (
        app_config_dir() / ".env",
        Path.cwd() / ".env",
    )
    return tuple(p for p in candidates if p.is_file())


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # Providers
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

    # Storage
    database_url: str = Field(
        default="sqlite:////home/you/.local/share/live-meeting-transcriber/app.db",
        alias="DATABASE_URL",
    )

    # Audio
    audio_chunk_seconds: int = Field(default=10, alias="AUDIO_CHUNK_SECONDS", ge=1, le=300)
    audio_sample_rate: int = Field(default=16000, alias="AUDIO_SAMPLE_RATE", ge=8000, le=48000)
    audio_channels: int = Field(default=1, alias="AUDIO_CHANNELS", ge=1, le=2)
    # When AUDIO_CHANNELS=2 and mic+monitor capture: ``mixdown`` = RMS mono for live ASR;
    # ``dual_path`` = transcribe L (mic) and R (system) separately (faster-whisper only).
    audio_stereo_mode: Literal["mixdown", "dual_path"] = Field(
        default="mixdown", alias="AUDIO_STEREO_MODE"
    )
    keep_audio_chunks: bool = Field(default=False, alias="KEEP_AUDIO_CHUNKS")
    audio_include_microphone: bool = Field(default=True, alias="AUDIO_INCLUDE_MICROPHONE")
    audio_microphone_source: str | None = Field(default=None, alias="AUDIO_MICROPHONE_SOURCE")

    # Logging
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

    # After full-session WhisperX pass (see ``live-transcriber finalize``).
    finalize_on_session_stop: bool = Field(default=False, alias="FINALIZE_ON_SESSION_STOP")

    # Offline WhisperX / pyannote (optional extra ``whisperx``)
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

    # Diarization (legacy chunk diarization removed; kept for HF token reuse / docs)
    diarization_enabled: bool = Field(default=False, alias="DIARIZATION_ENABLED")
    diarization_provider: str = Field(default="noop", alias="DIARIZATION_PROVIDER")
    hf_token: str | None = Field(default=None, alias="HF_TOKEN")
    pyannote_model: str = Field(
        default="pyannote/speaker-diarization-3.1",
        alias="PYANNOTE_MODEL",
    )
    # Hints for pyannote Pipeline(audio, **kwargs). When you know the meeting size, setting
    # DIARIZATION_NUM_SPEAKERS (or min/max) often fixes "everything is speaker_1" on mixed mono.
    diarization_num_speakers: int | None = Field(
        default=None, alias="DIARIZATION_NUM_SPEAKERS", ge=1, le=32
    )
    diarization_min_speakers: int | None = Field(
        default=None, alias="DIARIZATION_MIN_SPEAKERS", ge=1, le=32
    )
    diarization_max_speakers: int | None = Field(
        default=None, alias="DIARIZATION_MAX_SPEAKERS", ge=1, le=32
    )

    # Obsidian vault (optional): people folder for autocomplete + new person notes; meeting template export
    obsidian_people_dir: Path | None = Field(default=None, alias="OBSIDIAN_PEOPLE_DIR")
    obsidian_meetings_dir: Path | None = Field(default=None, alias="OBSIDIAN_MEETINGS_DIR")
    obsidian_meeting_template: Path | None = Field(default=None, alias="OBSIDIAN_MEETING_TEMPLATE")
    obsidian_person_template: Path | None = Field(default=None, alias="OBSIDIAN_PERSON_TEMPLATE")
    obsidian_screenshots_dir: Path | None = Field(default=None, alias="OBSIDIAN_SCREENSHOTS_DIR")

    # GNOME-style screenshots (filename timestamps matched to session UTC bounds)
    screenshots_export_enabled: bool = Field(default=True, alias="SCREENSHOTS_EXPORT_ENABLED")
    screenshots_source_dir: Path | None = Field(default=None, alias="SCREENSHOTS_SOURCE_DIR")

    # Video import slide detection (``live-transcriber transcribe-video``)
    video_slide_strategy: Literal["frame_diff", "ffmpeg_scene"] = Field(
        default="frame_diff", alias="VIDEO_SLIDE_STRATEGY"
    )
    video_slide_sample_interval_seconds: float = Field(
        default=2.0, alias="VIDEO_SLIDE_SAMPLE_INTERVAL_SECONDS", ge=0.5, le=30.0
    )
    video_slide_change_threshold: float = Field(
        default=0.12, alias="VIDEO_SLIDE_CHANGE_THRESHOLD", ge=0.01, le=1.0
    )
    video_slide_min_interval_seconds: float = Field(
        default=15.0, alias="VIDEO_SLIDE_MIN_INTERVAL_SECONDS", ge=0.0, le=600.0
    )
    video_slide_max_candidates: int = Field(
        default=120, alias="VIDEO_SLIDE_MAX_CANDIDATES", ge=1, le=500
    )

    @field_validator(
        "diarization_num_speakers",
        "diarization_min_speakers",
        "diarization_max_speakers",
        mode="before",
    )
    @classmethod
    def _optional_diarization_int(cls, v: object) -> int | None:
        if v is None or v == "":
            return None
        return int(v)

    @model_validator(mode="after")
    def _diarization_speaker_bounds(self) -> Settings:
        mn, mx = self.diarization_min_speakers, self.diarization_max_speakers
        if mn is not None and mx is not None and mn > mx:
            msg = "DIARIZATION_MIN_SPEAKERS must be <= DIARIZATION_MAX_SPEAKERS"
            raise ValueError(msg)
        return self

    @field_validator("faster_whisper_language", mode="before")
    @classmethod
    def _faster_whisper_language(cls, v: object) -> str | None:
        if v is None or v == "":
            return None
        return str(v).strip() or None

    @field_validator(
        "whisperx_device", "whisperx_torch_device", "whisperx_diarize_device", mode="before"
    )
    @classmethod
    def _optional_whisperx_device_str(cls, v: object) -> str | None:
        if v is None or v == "":
            return None
        s = str(v).strip()
        return s if s else None

    @field_validator(
        "obsidian_people_dir",
        "obsidian_meetings_dir",
        "obsidian_meeting_template",
        "obsidian_person_template",
        "obsidian_screenshots_dir",
        "screenshots_source_dir",
        mode="before",
    )
    @classmethod
    def _obsidian_paths(cls, v: object) -> Path | None:
        if v is None or v == "":
            return None
        return Path(str(v)).expanduser().resolve()

    def ensure_data_dir(self) -> Path:
        # Only used for default sqlite paths; callers should not rely on implicit globals.
        default_dir = Path.home() / ".local" / "share" / "live-meeting-transcriber"
        default_dir.mkdir(parents=True, exist_ok=True)
        return default_dir

    def effective_screenshots_source_dir(self) -> Path | None:
        """Directory to scan for ``Screenshot from YYYY-MM-DD HH-MM-SS`` files; ``None`` disables scanning."""
        if not self.screenshots_export_enabled:
            return None
        if self.screenshots_source_dir is not None:
            return self.screenshots_source_dir
        return (Path.home() / "Pictures" / "Screenshots").resolve()

    def effective_obsidian_screenshots_dir(self) -> Path | None:
        """Where to copy screenshots for Obsidian embeds; defaults next to Meetings folder."""
        if self.obsidian_screenshots_dir is not None:
            return self.obsidian_screenshots_dir
        if self.obsidian_meetings_dir is not None:
            return (self.obsidian_meetings_dir.parent / "Images" / "Screenshots").resolve()
        return None

    def resolved_log_file(self) -> Path:
        """Absolute path for the rotating application log (JSON lines)."""
        if self.log_file is not None:
            return Path(self.log_file).expanduser().resolve()
        return (self.ensure_data_dir() / "logs" / "live-meeting-transcriber.log").resolve()

    @property
    def log_file_max_bytes(self) -> int:
        return int(self.log_file_max_mb) * 1024 * 1024

    def effective_transcription_model_display(self) -> str:
        """Model name shown in UI / logs (OpenAI model id vs Whisper size)."""
        if self.transcription_provider == "faster_whisper":
            return self.faster_whisper_model
        return self.transcription_model

    def slide_detection_params(self) -> SlideDetectionParams:
        """Build domain slide detection params from current settings."""
        return SlideDetectionParams(
            sample_interval_seconds=self.video_slide_sample_interval_seconds,
            change_threshold=self.video_slide_change_threshold,
            min_slide_interval_seconds=self.video_slide_min_interval_seconds,
            max_candidates=self.video_slide_max_candidates,
        )

    def pyannote_diarization_pipeline_kwargs(self) -> dict[str, int]:
        """Keyword arguments for pyannote ``Pipeline.__call__(audio, **kwargs)``."""
        if self.diarization_num_speakers is not None:
            return {"num_speakers": int(self.diarization_num_speakers)}
        out: dict[str, int] = {}
        if self.diarization_min_speakers is not None:
            out["min_speakers"] = int(self.diarization_min_speakers)
        if self.diarization_max_speakers is not None:
            out["max_speakers"] = int(self.diarization_max_speakers)
        return out


def load_settings() -> Settings:
    env_files = discover_env_file_paths()
    if env_files:
        return Settings(_env_file=tuple(str(p) for p in env_files))
    return Settings()
