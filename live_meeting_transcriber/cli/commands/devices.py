"""``devices`` command — list audio capture sources."""

from __future__ import annotations

import typer

from live_meeting_transcriber.audio.platform import audio_backend
from live_meeting_transcriber.cli.deps import get_container


def devices(ctx: typer.Context) -> None:
    """List available audio capture devices (PulseAudio/PipeWire on Linux, AVFoundation on macOS)."""
    c = get_container(ctx)
    sources = c.devices.list_sources()
    default_monitor = c.devices.get_default_monitor_source()
    default_mic = c.devices.get_default_microphone_source()

    for s in sources:
        if default_monitor and s.name == default_monitor:
            prefix = "* "
        elif default_mic and s.name == default_mic:
            prefix = "^ "
        else:
            prefix = "  "
        if audio_backend() == "avfoundation":
            typer.echo(f"{prefix}{s.name}  {s.description}")
        else:
            typer.echo(f"{prefix}{s.name}")
    typer.echo("", err=False)
    typer.echo("* = default monitor (playback)   ^ = default microphone (capture)", err=False)
    if audio_backend() == "avfoundation" and default_monitor is None:
        typer.echo(
            "macOS: no virtual loopback detected — install BlackHole or route meeting audio "
            "through a virtual device, then set --source or AUDIO_MICROPHONE_SOURCE.",
            err=False,
        )
