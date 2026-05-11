from __future__ import annotations

import subprocess
from dataclasses import dataclass


class AudioDeviceError(RuntimeError):
    pass


@dataclass(frozen=True)
class PactlAudioSource:
    name: str
    description: str


class PactlAudioDeviceProvider:
    def list_sources(self) -> list[PactlAudioSource]:
        # pactl output: index \t name \t driver \t sample_spec \t state \t channels \t ...
        try:
            out = subprocess.run(
                ["pactl", "list", "short", "sources"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        except FileNotFoundError as e:
            raise AudioDeviceError("pactl not found; install pulseaudio-utils") from e
        except subprocess.CalledProcessError as e:
            raise AudioDeviceError(f"pactl failed: {e.stderr.strip()}") from e

        sources: list[PactlAudioSource] = []
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            name = parts[1].strip()
            desc = name
            sources.append(PactlAudioSource(name=name, description=desc))
        return sources

    def get_default_monitor_source(self) -> str | None:
        # Prefer Default Sink -> <sink>.monitor
        try:
            info = subprocess.run(
                ["pactl", "info"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        except Exception:
            return None

        default_sink: str | None = None
        for line in info.splitlines():
            if line.startswith("Default Sink:"):
                default_sink = line.split(":", 1)[1].strip()
                break
        if not default_sink:
            return None

        candidate = f"{default_sink}.monitor"
        names = {s.name for s in self.list_sources()}
        return candidate if candidate in names else None

