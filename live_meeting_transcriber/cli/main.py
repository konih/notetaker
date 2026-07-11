"""Typer CLI entry point.

This module is a thin router (ARCH-11): it builds the Typer app, wires the
per-command callback that constructs the application container, and registers the
command implementations that live under :mod:`live_meeting_transcriber.cli.commands`.
"""

from __future__ import annotations

import atexit

import typer

from live_meeting_transcriber.application.container import (
    ProviderSelectionError,
    build_container,
)

# Re-exported for backwards compatibility: tests patch ``cli.main.build_container`` /
# ``cli.main.load_settings`` (used by the callback below) and import
# ``cli.main._end_session_safely`` directly.
from live_meeting_transcriber.cli.commands import (
    cleanup as cleanup_cmd,
)
from live_meeting_transcriber.cli.commands import (
    devices as devices_cmd,
)
from live_meeting_transcriber.cli.commands import (
    finalize as finalize_cmd,
)
from live_meeting_transcriber.cli.commands import (
    paths as paths_cmd,
)
from live_meeting_transcriber.cli.commands import (
    recording as recording_cmd,
)
from live_meeting_transcriber.cli.commands import (
    sessions as sessions_cmd,
)
from live_meeting_transcriber.cli.commands import (
    video as video_cmd,
)
from live_meeting_transcriber.cli.deps import _end_session_safely, get_container
from live_meeting_transcriber.config.settings import load_settings
from live_meeting_transcriber.observability.logging import configure_logging

__all__ = ["_end_session_safely", "app", "build_container", "get_container", "load_settings"]

app = typer.Typer(
    add_completion=False,
    help="Live background meeting transcription (Linux and macOS).",
)
slides_app = typer.Typer(help="Preview and apply slide detection on imported video sessions.")
app.add_typer(slides_app, name="slides")


@app.callback(invoke_without_command=True)
def _main_callback(ctx: typer.Context) -> None:
    settings = load_settings()
    # ``paths`` is pure output consumed by scripts (the macOS installer captures
    # ``paths --config-dir``): skip logging setup so stdout stays machine-readable
    # (structlog's console renderer writes the ``logging_configured`` event to stdout).
    if ctx.invoked_subcommand == "paths":
        return
    log_path = settings.resolved_log_file() if settings.log_enable_file else None
    configure_logging(
        settings.log_level,
        log_file=log_path,
        log_file_max_bytes=settings.log_file_max_bytes,
        log_file_backup_count=settings.log_file_backup_count,
    )
    # ``doctor`` is a self-contained diagnostic that must run even when transcription
    # providers are not configured yet (e.g. no OPENAI_API_KEY) — skip the container build.
    if ctx.invoked_subcommand == "doctor":
        return
    try:
        container = build_container(settings)
    except ProviderSelectionError as e:
        # Provider misconfiguration (e.g. missing OPENAI_API_KEY) is a user error,
        # not a bug: show the actionable message instead of a Python traceback.
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2) from e
    atexit.register(container.close)
    ctx.obj = container

    if ctx.invoked_subcommand is None:
        from live_meeting_transcriber.ui.tui.app import run_tui_attached

        run_tui_attached(
            container=container,
            settings=settings,
            configure_log=False,
        )
        raise typer.Exit()


@app.command()
def tui(ctx: typer.Context) -> None:
    """Interactive terminal UI (live status, transcript, settings)."""
    from live_meeting_transcriber.ui.tui.app import run_tui_attached

    run_tui_attached(
        container=get_container(ctx),
        settings=load_settings(),
        configure_log=False,
    )


# --- Command registration (thin router) -------------------------------------------------
app.command()(devices_cmd.devices)
app.command()(sessions_cmd.sessions)
app.command()(recording_cmd.record)
app.command()(sessions_cmd.summarize)
app.command()(sessions_cmd.export)
app.command("finalize")(finalize_cmd.finalize_session)
app.command("finalize-pending")(finalize_cmd.finalize_pending)
app.command("doctor")(finalize_cmd.doctor)
app.command("paths")(paths_cmd.paths)
app.command("speakers")(sessions_cmd.list_speakers)
app.command("transcribe-video")(video_cmd.transcribe_video)
app.command()(cleanup_cmd.cleanup)
app.command("speaker-alias")(sessions_cmd.speaker_alias)

slides_app.command("preview")(video_cmd.slides_preview)
slides_app.command("apply")(video_cmd.slides_apply)
