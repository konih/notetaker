"""Characterization of audio backend/platform selection (T2).

Pure OS-detection helpers — locking the version parsing and platform mapping that
gate Core Audio tap support. Hermetic: ``sys.platform`` / ``platform.mac_ver`` are
monkeypatched; no real OS calls.
"""

from __future__ import annotations

import platform as _platform
import sys

import pytest
from live_meeting_transcriber.audio import platform as platform_mod


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("14.4", True),
        ("14.4.1", True),
        ("14.5", True),
        ("15.0", True),
        ("26.5", True),
        ("14.3", False),
        ("14.3.9", False),
        ("14.0", False),
        ("13.9", False),
        ("14", False),  # bare major -> minor defaults to 0 -> < 14.4
        ("", False),
        ("sonoma", False),  # non-numeric -> no parts -> False
        ("14.x", False),  # stops at first non-digit -> (14, 0) -> False
    ],
)
def test_mac_version_supports_coreaudio_tap(version: str, expected: bool) -> None:
    assert platform_mod.mac_version_supports_coreaudio_tap(version) is expected


def test_audio_backend_darwin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    assert platform_mod.audio_backend() == "avfoundation"


def test_audio_backend_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    assert platform_mod.audio_backend() == "pulse"


@pytest.mark.parametrize(
    ("plat", "label"),
    [("darwin", "macOS"), ("linux", "Linux"), ("linux2", "Linux"), ("win32", "win32")],
)
def test_platform_label(monkeypatch: pytest.MonkeyPatch, plat: str, label: str) -> None:
    monkeypatch.setattr(sys, "platform", plat)
    assert platform_mod.platform_label() == label


def test_macos_supports_coreaudio_tap_off_darwin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    assert platform_mod.macos_supports_coreaudio_tap() is False


def test_macos_supports_coreaudio_tap_on_supported_darwin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(_platform, "mac_ver", lambda: ("14.4.1", ("", "", ""), ""))
    assert platform_mod.macos_supports_coreaudio_tap() is True


def test_macos_supports_coreaudio_tap_on_old_darwin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(_platform, "mac_ver", lambda: ("14.3", ("", "", ""), ""))
    assert platform_mod.macos_supports_coreaudio_tap() is False
