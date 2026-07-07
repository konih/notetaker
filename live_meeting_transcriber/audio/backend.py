from __future__ import annotations

from live_meeting_transcriber.audio.avfoundation_devices import AvfoundationAudioDeviceProvider
from live_meeting_transcriber.audio.capture import FfmpegAudioCapture
from live_meeting_transcriber.audio.devices import PactlAudioDeviceProvider
from live_meeting_transcriber.audio.platform import audio_backend
from live_meeting_transcriber.domain.ports import AudioCapture, AudioDeviceProvider


def build_audio_device_provider() -> AudioDeviceProvider:
    if audio_backend() == "avfoundation":
        return AvfoundationAudioDeviceProvider()
    return PactlAudioDeviceProvider()


def build_audio_capture() -> AudioCapture:
    return FfmpegAudioCapture(backend=audio_backend())
