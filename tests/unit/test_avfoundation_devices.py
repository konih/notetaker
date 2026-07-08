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


# When a real loopback driver (BlackHole) and an app-specific virtual device
# (the "Microsoft Teams Audio Device") are both present, the real loopback must
# win. The Teams device matches the "teams audio" hint but only carries audio
# when Teams routes system sound, so auto-picking it silently drops remote audio.
_SAMPLE_FFMPEG_LIST_WITH_BLACKHOLE = """
[AVFoundation indev @ 0x87cc1c140] AVFoundation audio devices:
[AVFoundation indev @ 0x87cc1c140] [0] MacBook Pro-Mikrofon
[AVFoundation indev @ 0x87cc1c140] [1] Microsoft Teams Audio
[AVFoundation indev @ 0x87cc1c140] [2] BlackHole 2ch
[in#0 @ 0x87cc1c000] Error opening input: Input/output error
"""


def test_avfoundation_default_monitor_prefers_blackhole_over_teams() -> None:
    provider = AvfoundationAudioDeviceProvider()
    provider.list_sources = (  # type: ignore[method-assign]
        lambda: parse_avfoundation_audio_devices(_SAMPLE_FFMPEG_LIST_WITH_BLACKHOLE)
    )
    # BlackHole (:2) must beat the earlier-indexed Teams device (:1).
    assert provider.get_default_monitor_source() == ":2"


def test_avfoundation_default_microphone_prefers_builtin() -> None:
    provider = AvfoundationAudioDeviceProvider()
    provider.list_sources = lambda: parse_avfoundation_audio_devices(_SAMPLE_FFMPEG_LIST)  # type: ignore[method-assign]
    assert provider.get_default_microphone_source() == ":3"
