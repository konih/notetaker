from __future__ import annotations

from live_meeting_transcriber.audio.avfoundation_devices import AvfoundationAudioDeviceProvider
from live_meeting_transcriber.audio.capture import FfmpegAudioCapture
from live_meeting_transcriber.audio.coreaudio_tap import MacosAudioCapture
from live_meeting_transcriber.audio.devices import PactlAudioDeviceProvider
from live_meeting_transcriber.audio.platform import audio_backend
from live_meeting_transcriber.domain.ports import AudioCapture, AudioDeviceProvider

MacosSystemCapture = str  # "auto" | "coreaudio_tap" | "avfoundation"


def _prefer_coreaudio_tap(macos_system_capture: MacosSystemCapture) -> bool:
    """Whether to offer/prefer the native tap. ``avfoundation`` opts out; the provider still
    gates on actual OS support (macOS 14.4+)."""
    return macos_system_capture != "avfoundation"


def build_audio_device_provider(
    macos_system_capture: MacosSystemCapture = "auto",
) -> AudioDeviceProvider:
    if audio_backend() == "avfoundation":
        return AvfoundationAudioDeviceProvider(
            prefer_coreaudio_tap=_prefer_coreaudio_tap(macos_system_capture)
        )
    return PactlAudioDeviceProvider()


def build_audio_capture(macos_system_capture: MacosSystemCapture = "auto") -> AudioCapture:
    if audio_backend() == "avfoundation":
        # Routes by source: the tap sentinel → native Core Audio tap; a ``:N`` device
        # (incl. BlackHole) → ffmpeg avfoundation.
        return MacosAudioCapture()
    return FfmpegAudioCapture(backend=audio_backend())
