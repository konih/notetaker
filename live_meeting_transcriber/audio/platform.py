from __future__ import annotations

import sys
from typing import Literal

AudioBackend = Literal["pulse", "avfoundation"]


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
