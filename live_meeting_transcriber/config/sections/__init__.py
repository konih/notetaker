"""Per-area settings section models (A8, ARCH-17).

Each module declares one configuration area as a ``BaseSettings`` subclass with
flat ``Field(alias="ENV_VAR")`` declarations plus its area-local validators and
helpers. The aggregate ``config.settings.Settings`` multiple-inherits every
section, so pydantic collects all fields onto one flat model — env-var aliases,
precedence, and ``Settings(field_name=...)`` construction are exactly as before
the split. Sections are not meant to be instantiated on their own.
"""

from live_meeting_transcriber.config.sections.audio import AudioSettings
from live_meeting_transcriber.config.sections.diarization import DiarizationSettings
from live_meeting_transcriber.config.sections.logging import LoggingSettings
from live_meeting_transcriber.config.sections.obsidian import ObsidianSettings, ScreenshotSettings
from live_meeting_transcriber.config.sections.offline import WhisperXSettings
from live_meeting_transcriber.config.sections.providers import ProviderSettings
from live_meeting_transcriber.config.sections.storage import StorageSettings
from live_meeting_transcriber.config.sections.video import VideoSettings

__all__ = [
    "AudioSettings",
    "DiarizationSettings",
    "LoggingSettings",
    "ObsidianSettings",
    "ProviderSettings",
    "ScreenshotSettings",
    "StorageSettings",
    "VideoSettings",
    "WhisperXSettings",
]
