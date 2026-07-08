from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

from live_meeting_transcriber.audio.coreaudio_tap import (
    COREAUDIO_TAP_DESCRIPTION,
    COREAUDIO_TAP_SOURCE,
)
from live_meeting_transcriber.audio.devices import AudioDeviceError
from live_meeting_transcriber.audio.platform import macos_supports_coreaudio_tap

_DEVICE_LINE_RE = re.compile(r"^\[AVFoundation indev @ .+\] \[(\d+)\] (.+)$")

# Virtual loopback / meeting-capture devices (system audio on macOS).
#
# Ordered by preference: ``get_default_monitor_source`` picks the first *hint* (not the
# first device) that any device matches, so real loopback drivers rank above app-specific
# virtual devices. The "Microsoft Teams Audio Device" matches ``teams audio`` but only
# carries audio when Teams routes system sound, so it is a last-resort fallback — never let
# it shadow a real BlackHole/Loopback device that reliably taps system output.
_MONITOR_HINTS = (
    # Reliable general-purpose loopback drivers first.
    "blackhole",
    "loopback",
    "soundflower",
    "vb-audio",
    "monitor",
    "system audio",
    "virtual",
    # App-specific virtual devices last (present but unreliable as a system tap).
    "teams audio",
    "zoom",
)

# Built-in or headset mics — avoid virtual meeting devices.
_BUILTIN_MIC_HINTS = ("macbook", "built-in", "internal")
_MIC_HINTS = (
    "mikrofon",
    "microphone",
    "headset",
    "airpods",
)


@dataclass(frozen=True)
class AvfoundationAudioSource:
    name: str
    description: str


def parse_avfoundation_audio_devices(stdout: str) -> list[AvfoundationAudioSource]:
    """Parse ``ffmpeg -f avfoundation -list_devices true`` audio section."""
    in_audio = False
    sources: list[AvfoundationAudioSource] = []
    for line in stdout.splitlines():
        if "AVFoundation audio devices:" in line:
            in_audio = True
            continue
        if not in_audio:
            continue
        match = _DEVICE_LINE_RE.match(line.strip())
        if not match:
            continue
        idx, label = match.group(1), match.group(2).strip()
        sources.append(AvfoundationAudioSource(name=f":{idx}", description=label))
    return sources


def _label_lower(source: AvfoundationAudioSource) -> str:
    return source.description.casefold()


def _matches_any(label: str, hints: tuple[str, ...]) -> bool:
    return any(hint in label for hint in hints)


class AvfoundationAudioDeviceProvider:
    """Lists macOS capture devices via ffmpeg AVFoundation.

    When ``prefer_coreaudio_tap`` is set and the OS supports it (macOS 14.4+), the native
    Core Audio system-audio tap is surfaced as a synthetic source and chosen as the default
    monitor — so system audio works without installing BlackHole. The BlackHole/loopback
    device path stays available as a fallback.
    """

    def __init__(self, *, prefer_coreaudio_tap: bool = False) -> None:
        self._prefer_coreaudio_tap = prefer_coreaudio_tap

    def _coreaudio_tap_enabled(self) -> bool:
        return self._prefer_coreaudio_tap and macos_supports_coreaudio_tap()

    def _list_device_sources(self) -> list[AvfoundationAudioSource]:
        try:
            proc = subprocess.run(
                ["ffmpeg", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
                check=False,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as e:
            raise AudioDeviceError(
                "ffmpeg not found; install ffmpeg (e.g. brew install ffmpeg)"
            ) from e

        # ffmpeg exits non-zero when listing devices; stderr/stdout both carry the list.
        combined = f"{proc.stdout}\n{proc.stderr}"
        sources = parse_avfoundation_audio_devices(combined)
        if not sources:
            detail = (proc.stderr or proc.stdout or "").strip()
            raise AudioDeviceError(detail or "ffmpeg listed no AVFoundation audio devices")
        return sources

    def list_sources(self) -> list[AvfoundationAudioSource]:
        tap = AvfoundationAudioSource(
            name=COREAUDIO_TAP_SOURCE, description=COREAUDIO_TAP_DESCRIPTION
        )
        if not self._coreaudio_tap_enabled():
            return self._list_device_sources()
        try:
            return [tap, *self._list_device_sources()]
        except AudioDeviceError:
            # The native tap needs no enumerable device, so still offer it.
            return [tap]

    def get_default_monitor_source(self) -> str | None:
        # F7: prefer the driver-free native tap so system audio works without BlackHole.
        if self._coreaudio_tap_enabled():
            return COREAUDIO_TAP_SOURCE
        sources = self.list_sources()
        # Iterate hints in preference order (not device order) so a reliable loopback
        # driver always beats an app-specific virtual device that happens to enumerate
        # first (e.g. "Microsoft Teams Audio Device").
        for hint in _MONITOR_HINTS:
            for source in sources:
                if hint in _label_lower(source):
                    return source.name
        return None

    def get_default_microphone_source(self) -> str | None:
        # The synthetic tap source carries a "system audio" label, so it is filtered out below.
        sources = self.list_sources()
        for hints in (_BUILTIN_MIC_HINTS, _MIC_HINTS):
            for source in sources:
                label = _label_lower(source)
                if _matches_any(label, _MONITOR_HINTS):
                    continue
                if _matches_any(label, hints):
                    return source.name
        for source in sources:
            if not _matches_any(_label_lower(source), _MONITOR_HINTS):
                return source.name
        return None
