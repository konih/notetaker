"""``live-transcriber paths`` — resolved filesystem locations (F5).

Single source of truth for "where does the app read config / keep data", so the
macOS installer and support workflows never duplicate the platform rules in shell.
Runs without provider configuration (no ``OPENAI_API_KEY`` needed), like ``doctor``.
"""

from __future__ import annotations

import typer

from live_meeting_transcriber.config.paths import (
    app_config_dir,
    default_config_yaml_path,
    default_data_dir,
    discover_env_file_paths,
)
from live_meeting_transcriber.config.settings import load_settings


def paths(
    config_dir: bool = typer.Option(
        False,
        "--config-dir",
        help="Print only the config directory path (machine-readable, for scripts).",
    ),
) -> None:
    """Show where this machine's config, data, database, and logs live."""
    if config_dir:
        typer.echo(str(app_config_dir()))
        return

    settings = load_settings()
    env_files = discover_env_file_paths()
    env_display = ", ".join(str(p) for p in env_files) if env_files else "(none found)"
    log_display = (
        str(settings.resolved_log_file()) if settings.log_enable_file else "(file logging disabled)"
    )

    typer.echo(f"Config directory: {app_config_dir()}")
    typer.echo(f"Settings store:   {default_config_yaml_path()}")
    typer.echo(f".env files:       {env_display}")
    typer.echo(f"Data directory:   {default_data_dir()}")
    typer.echo(f"Database URL:     {settings.database_url}")
    typer.echo(f"Log file:         {log_display}")
