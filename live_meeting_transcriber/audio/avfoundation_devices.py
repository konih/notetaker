from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

from live_meeting_transcriber.audio.devices import AudioDeviceError

_DEVICE_LINE_RE = re.compile(r"^\[AVFoundation indev @ .+\] \[(\d+)\] (.+)$")

# Virtual loopback / meeting-capture devices (system audio on macOS).
_MONITOR_HINTS = (
    "blackhole",
    "loopback",
    "soundflower",
    "teams audio",
    "zoom",
    "monitor",
    "system audio",
    "vb-audio",
    "virtual",
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
    """Lists macOS capture devices via ffmpeg AVFoundation."""

    def list_sources(self) -> list[AvfoundationAudioSource]:
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

    def get_default_monitor_source(self) -> str | None:
        sources = self.list_sources()
        for source in sources:
            if _matches_any(_label_lower(source), _MONITOR_HINTS):
                return source.name
        return None

    def get_default_microphone_source(self) -> str | None:
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
