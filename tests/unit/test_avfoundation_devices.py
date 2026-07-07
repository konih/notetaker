from __future__ import annotations

from live_meeting_transcriber.audio.avfoundation_devices import (
    AvfoundationAudioDeviceProvider,
    parse_avfoundation_audio_devices,
)

_SAMPLE_FFMPEG_LIST = """
[AVFoundation indev @ 0x87cc1c140] AVFoundation video devices:
[AVFoundation indev @ 0x87cc1c140] [0] FaceTime HD Camera
[AVFoundation indev @ 0x87cc1c140] AVFoundation audio devices:
[AVFoundation indev @ 0x87cc1c140] [0] USB Audio Device
[AVFoundation indev @ 0x87cc1c140] [1] Mikrofon von „Apple-GVQV63L23R“
[AVFoundation indev @ 0x87cc1c140] [2] Logi 4K Stream Edition
[AVFoundation indev @ 0x87cc1c140] [3] MacBook Pro-Mikrofon
[AVFoundation indev @ 0x87cc1c140] [4] Konrad's AirPods Pro
[AVFoundation indev @ 0x87cc1c140] [5] Microsoft Teams Audio
[in#0 @ 0x87cc1c000] Error opening input: Input/output error
"""


def test_parse_avfoundation_audio_devices_ignores_video_section() -> None:
    sources = parse_avfoundation_audio_devices(_SAMPLE_FFMPEG_LIST)
    assert [s.name for s in sources] == [":0", ":1", ":2", ":3", ":4", ":5"]
    assert sources[3].description == "MacBook Pro-Mikrofon"
    assert sources[5].description == "Microsoft Teams Audio"


def test_avfoundation_default_monitor_prefers_virtual_loopback() -> None:
    provider = AvfoundationAudioDeviceProvider()
    provider.list_sources = lambda: parse_avfoundation_audio_devices(_SAMPLE_FFMPEG_LIST)  # type: ignore[method-assign]
    assert provider.get_default_monitor_source() == ":5"


def test_avfoundation_default_microphone_prefers_builtin() -> None:
    provider = AvfoundationAudioDeviceProvider()
    provider.list_sources = lambda: parse_avfoundation_audio_devices(_SAMPLE_FFMPEG_LIST)  # type: ignore[method-assign]
    assert provider.get_default_microphone_source() == ":3"
