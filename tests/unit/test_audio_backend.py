"""Characterization of audio adapter selection (T2).

``build_audio_capture`` / ``build_audio_device_provider`` pick the concrete adapter
from the detected backend. Lock the dispatch (which type is returned per backend, and
how ``macos_system_capture`` toggles the native-tap preference) by monkeypatching
``audio_backend``. No real audio/OS access.
"""

from __future__ import annotations

import pytest
from live_meeting_transcriber.audio import backend as backend_mod
from live_meeting_transcriber.audio.avfoundation_devices import AvfoundationAudioDeviceProvider
from live_meeting_transcriber.audio.capture import FfmpegAudioCapture
from live_meeting_transcriber.audio.coreaudio_tap import MacosAudioCapture
from live_meeting_transcriber.audio.devices import PactlAudioDeviceProvider


@pytest.mark.parametrize(
    ("mode", "expected"),
    [("auto", True), ("coreaudio_tap", True), ("avfoundation", False)],
)
def test_prefer_coreaudio_tap(mode: str, expected: bool) -> None:
    assert backend_mod._prefer_coreaudio_tap(mode) is expected


def test_build_capture_pulse(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backend_mod, "audio_backend", lambda: "pulse")
    cap = backend_mod.build_audio_capture()
    assert isinstance(cap, FfmpegAudioCapture)


def test_build_capture_avfoundation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backend_mod, "audio_backend", lambda: "avfoundation")
    cap = backend_mod.build_audio_capture()
    assert isinstance(cap, MacosAudioCapture)


def test_build_device_provider_pulse(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backend_mod, "audio_backend", lambda: "pulse")
    prov = backend_mod.build_audio_device_provider()
    assert isinstance(prov, PactlAudioDeviceProvider)


def test_build_device_provider_avfoundation_prefers_tap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backend_mod, "audio_backend", lambda: "avfoundation")
    prov = backend_mod.build_audio_device_provider(macos_system_capture="auto")
    assert isinstance(prov, AvfoundationAudioDeviceProvider)
    assert prov._prefer_coreaudio_tap is True


def test_build_device_provider_avfoundation_opts_out_of_tap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(backend_mod, "audio_backend", lambda: "avfoundation")
    prov = backend_mod.build_audio_device_provider(macos_system_capture="avfoundation")
    assert isinstance(prov, AvfoundationAudioDeviceProvider)
    assert prov._prefer_coreaudio_tap is False
