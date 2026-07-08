from __future__ import annotations

import platform as _platform
import sys
from typing import Literal

AudioBackend = Literal["pulse", "avfoundation"]

# Core Audio process taps (the driver-free "BlackHole alternative") are only reliable from
# macOS 14.4 onward — the API constants landed in 14.2 but the TCC prompt behaviour was
# unstable on 14.2-14.3, so 14.4 is the practical floor.
_COREAUDIO_TAP_MIN = (14, 4)


def audio_backend() -> AudioBackend:
    if sys.platform == "darwin":
        return "avfoundation"
    return "pulse"


def platform_label() -> str:
    if sys.platform == "darwin":
        return "macOS"
    if sys.platform.startswith("linux"):
        return "Linux"
    return sys.platform


def mac_version_supports_coreaudio_tap(version: str) -> bool:
    """True when a macOS version string (e.g. ``"14.4.1"``) is >= the 14.4 tap floor."""
    parts: list[int] = []
    for piece in version.split("."):
        if not piece.isdigit():
            break
        parts.append(int(piece))
    if not parts:
        return False
    major = parts[0]
    minor = parts[1] if len(parts) > 1 else 0
    return (major, minor) >= _COREAUDIO_TAP_MIN


def macos_supports_coreaudio_tap() -> bool:
    """True when running on macOS with Core Audio process-tap support (14.4+)."""
    if sys.platform != "darwin":
        return False
    return mac_version_supports_coreaudio_tap(_platform.mac_ver()[0])
