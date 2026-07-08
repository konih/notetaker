from __future__ import annotations

import pytest
from live_meeting_transcriber.audio import avfoundation_devices, platform
from live_meeting_transcriber.audio.avfoundation_devices import (
    AvfoundationAudioDeviceProvider,
    AvfoundationAudioSource,
)
from live_meeting_transcriber.audio.coreaudio_tap import COREAUDIO_TAP_SOURCE


@pytest.mark.parametrize(
    ("version", "supported"),
    [
        ("14.4", True),
        ("14.4.1", True),
        ("15.0", True),
        ("26.5.1", True),
        ("14.3", False),
        ("14.2", False),
        ("13.6", False),
        ("", False),
    ],
)
def test_mac_version_supports_coreaudio_tap(version: str, supported: bool) -> None:
    assert platform.mac_version_supports_coreaudio_tap(version) is supported


def _provider_with_sources(
    monkeypatch: pytest.MonkeyPatch,
    sources: list[AvfoundationAudioSource],
    *,
    prefer_tap: bool,
    supported: bool = True,
) -> AvfoundationAudioDeviceProvider:
    monkeypatch.setattr(avfoundation_devices, "macos_supports_coreaudio_tap", lambda: supported)
    provider = AvfoundationAudioDeviceProvider(prefer_coreaudio_tap=prefer_tap)
    monkeypatch.setattr(provider, "list_sources", lambda: sources)
    return provider


def test_default_monitor_prefers_tap_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider_with_sources(
        monkeypatch,
        [AvfoundationAudioSource(name=":0", description="MacBook Pro Microphone")],
        prefer_tap=True,
    )
    assert provider.get_default_monitor_source() == COREAUDIO_TAP_SOURCE


def test_default_monitor_prefers_tap_even_over_blackhole(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider_with_sources(
        monkeypatch,
        [AvfoundationAudioSource(name=":2", description="BlackHole 2ch")],
        prefer_tap=True,
    )
    # the whole point of F7: don't require the third-party driver
    assert provider.get_default_monitor_source() == COREAUDIO_TAP_SOURCE


def test_default_monitor_uses_blackhole_when_tap_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider_with_sources(
        monkeypatch,
        [AvfoundationAudioSource(name=":2", description="BlackHole 2ch")],
        prefer_tap=False,
    )
    assert provider.get_default_monitor_source() == ":2"


def test_default_monitor_falls_back_when_tap_unsupported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider_with_sources(
        monkeypatch,
        [AvfoundationAudioSource(name=":2", description="BlackHole 2ch")],
        prefer_tap=True,
        supported=False,  # e.g. macOS 13
    )
    assert provider.get_default_monitor_source() == ":2"


def test_list_sources_includes_synthetic_tap_when_preferred(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(avfoundation_devices, "macos_supports_coreaudio_tap", lambda: True)

    def fake_ffmpeg_sources() -> list[AvfoundationAudioSource]:
        return [AvfoundationAudioSource(name=":0", description="MacBook Pro Microphone")]

    provider = AvfoundationAudioDeviceProvider(prefer_coreaudio_tap=True)
    monkeypatch.setattr(provider, "_list_device_sources", fake_ffmpeg_sources)

    names = [s.name for s in provider.list_sources()]
    assert COREAUDIO_TAP_SOURCE in names
