"""First-run / empty-state copy and startup prerequisite checks (U10).

Pure helpers so the empty-state wording and the non-blocking startup audio
checks can be unit-tested without mounting the Textual app. The UI layer
(``app.py`` / ``meeting_browser.py``) renders these strings and dispatches the
returned warnings; nothing here touches a provider or blocks launch.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

# Rich-markup hints shown when a surface has no content yet. Each names the
# concrete next keystroke so a blank pane never leaves the user guessing.
LIVE_EMPTY_HINT = (
    "[dim]No transcript yet. Press [/][bold]r[/][dim] to start recording, "
    "or [/][bold]ctrl+2[/][dim] to browse past meetings.[/]"
)
MEETINGS_EMPTY_HINT = (
    "No meetings yet. Go to the Live tab ([bold]ctrl+1[/]) and press "
    "[bold]r[/] to record your first meeting, or [bold]ctrl+v[/] to import a video."
)
SESSIONS_EMPTY_HINT = (
    "No sessions recorded yet — switch to the Live tab and press [bold]r[/] to start one."
)


def audio_prerequisite_warnings(list_sources: Callable[[], Sequence[object]]) -> list[str]:
    """Non-blocking startup checks for audio-capture prerequisites.

    Returns actionable remediation messages; an empty list means the basic
    prerequisites look satisfied. Never raises — a failing probe becomes a
    warning, so the app always finishes launching.
    """
    try:
        sources = list(list_sources())
    except Exception as e:  # probing needs ffmpeg (+ PortAudio on Linux); failure is non-fatal
        return [
            f"Audio device probing failed ({e}). Recording may not work — check that "
            "ffmpeg (and PortAudio on Linux) are installed and on PATH."
        ]
    if not sources:
        return [
            "No audio input devices detected. Connect a microphone or enable a "
            "monitor/loopback source, then reopen Audio sources (press a)."
        ]
    return []
