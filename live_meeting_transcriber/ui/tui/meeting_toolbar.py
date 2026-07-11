"""U9 — Meetings toolbar action catalog.

Single source of truth for the Meetings toolbar. Splitting the ten actions into a
small primary set (always-visible buttons) plus an overflow set (reached via a
"More…" menu) keeps the toolbar on one row instead of wrapping at narrow widths.

Pure data only — no Textual imports — so the partitioning is unit-testable without
mounting the app.
"""

from __future__ import annotations

from dataclasses import dataclass

MORE_BUTTON_ID = "meeting-btn-more"


@dataclass(frozen=True)
class ToolbarAction:
    """One Meetings toolbar action.

    ``action`` is the name of the ``MeetingBrowser`` coroutine method invoked when
    the button (or its overflow-menu entry) is activated.
    """

    button_id: str
    label: str
    action: str
    variant: str = "default"
    primary: bool = False
    # Hover tooltip (F10): lets a width-budgeted short label carry an honest,
    # longer explanation (e.g. that Speaker ID is a full retranscribe).
    tooltip: str | None = None


# Ordered as they should appear. ``continue-record`` and ``slide-preview`` stay
# primary because their disabled state is toggled via query_one() on selection —
# keeping them mounted avoids NoMatches. ``delete`` is a visible primary button
# (U24): its only keyboard trigger used to be a dead chord (ctrl+shift+d) and it was
# otherwise buried in the overflow menu, so deletion appeared not to work at all. The
# ``error`` variant renders it red, and the confirm modal still guards it.
MEETING_TOOLBAR_ACTIONS: tuple[ToolbarAction, ...] = (
    ToolbarAction("meeting-btn-save", "Save", "action_save_meeting", "primary", primary=True),
    ToolbarAction("meeting-btn-summarize", "Summarize", "action_summarize_meeting", primary=True),
    # Label trimmed "Export markdown" → "Export" so the primary row (now including the
    # promoted Speaker ID button) still fits the 120-col baseline without overflowing.
    ToolbarAction("meeting-btn-export", "Export", "action_export_meeting", primary=True),
    ToolbarAction(
        "meeting-btn-continue-record",
        "Continue recording",
        "action_continue_recording",
        primary=True,
    ),
    ToolbarAction(
        "meeting-btn-slide-preview", "Slide preview", "action_slide_preview", primary=True
    ),
    ToolbarAction("meeting-btn-import-video", "Import video", "action_import_video", "success"),
    # Speaker ID stays primary (P0): its only keyboard trigger used to be ``ctrl+i``,
    # which terminals collapse onto Tab (0x09) so the binding never fired — leaving the
    # buried overflow menu as the sole path. A visible button makes finalizing a past
    # meeting reachable with a click, independent of the keyboard.
    # The label stays short for the 120-col primary-row budget; the tooltip (and
    # the canonical "Speaker ID / Retranscribe" binding label) make its
    # full-retranscribe behaviour visible (F10, OQ-F10-2: one action, one name).
    ToolbarAction(
        "meeting-btn-speaker-id",
        "Speaker ID",
        "action_finalize_selected_speakers",
        "success",
        primary=True,
        tooltip=(
            "Full retranscribe: re-runs WhisperX transcription + speaker "
            "diarization and replaces this meeting's transcript."
        ),
    ),
    ToolbarAction("meeting-btn-delete", "Delete", "action_delete_meeting", "error", primary=True),
    ToolbarAction("meeting-btn-edit-line", "Edit line", "action_edit_segment"),
    ToolbarAction("meeting-btn-refresh", "Refresh", "action_refresh_list"),
)


def primary_toolbar_actions() -> list[ToolbarAction]:
    """Actions rendered as always-visible toolbar buttons."""
    return [a for a in MEETING_TOOLBAR_ACTIONS if a.primary]


def overflow_toolbar_actions() -> list[ToolbarAction]:
    """Actions reached through the "More…" overflow menu."""
    return [a for a in MEETING_TOOLBAR_ACTIONS if not a.primary]


def toolbar_action_by_button_id(button_id: str) -> ToolbarAction | None:
    """Look up an action by its button id, or ``None`` if unknown."""
    for a in MEETING_TOOLBAR_ACTIONS:
        if a.button_id == button_id:
            return a
    return None
