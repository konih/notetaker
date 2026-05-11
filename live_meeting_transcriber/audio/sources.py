from __future__ import annotations

from live_meeting_transcriber.config.settings import Settings
from live_meeting_transcriber.domain.ports import AudioDeviceProvider


def resolve_microphone_source(
    settings: Settings,
    devices: AudioDeviceProvider,
    *,
    cli_explicit: str | None = None,
    cli_no_microphone: bool = False,
) -> str | None:
    """PulseAudio source name for the microphone leg of a monitor+mic mix, or None for monitor-only."""
    if cli_no_microphone or not settings.audio_include_microphone:
        return None
    if cli_explicit is not None and cli_explicit.strip():
        return cli_explicit.strip()
    if (
        settings.audio_microphone_source is not None
        and str(settings.audio_microphone_source).strip()
    ):
        return str(settings.audio_microphone_source).strip()
    return devices.get_default_microphone_source()
