"""Shared CLI dependencies: container access + safe session teardown.

These helpers are used by every command module under :mod:`cli.commands`; keeping
them here lets ``cli/main.py`` stay a thin router (ARCH-11).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import typer

from live_meeting_transcriber.application.container import Container
from live_meeting_transcriber.domain.ports import MeetingSessionRepository


def get_container(ctx: typer.Context) -> Container:
    c = ctx.obj
    if not isinstance(c, Container):
        raise typer.Exit(code=2)
    return c


def _end_session_safely(sessions: MeetingSessionRepository, session_id: UUID, *, log: Any) -> None:
    """End a session, surfacing a failed end instead of silently swallowing it (ARCH-07).

    A failed ``sessions.end`` is logged and reported to stderr; the clean
    ``session_ended`` event is only emitted when the end actually succeeded.
    """
    try:
        sessions.end(session_id)
    except Exception:
        log.warning("session_end_failed", session_id=str(session_id), exc_info=True)
        typer.echo(
            "warning: failed to finalize the session cleanly; see logs for details",
            err=True,
        )
    else:
        log.info("session_ended", session_id=str(session_id))
