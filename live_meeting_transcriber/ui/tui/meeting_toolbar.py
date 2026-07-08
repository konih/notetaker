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


# Ordered as they should appear. ``continue-record`` and ``slide-preview`` stay
# primary because their disabled state is toggled via query_one() on selection —
# keeping them mounted avoids NoMatches. ``delete`` is destructive, so it lives in
# the overflow menu rather than a stray always-visible button.
MEETING_TOOLBAR_ACTIONS: tuple[ToolbarAction, ...] = (
    ToolbarAction("meeting-btn-save", "Save", "action_save_meeting", "primary", primary=True),
    ToolbarAction("meeting-btn-summarize", "Summarize", "action_summarize_meeting", primary=True),
    ToolbarAction("meeting-btn-export", "Export markdown", "action_export_meeting", primary=True),
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
    ToolbarAction(
        "meeting-btn-speaker-id", "Speaker ID", "action_finalize_selected_speakers", "success"
    ),
    ToolbarAction("meeting-btn-edit-line", "Edit line", "action_edit_segment"),
    ToolbarAction("meeting-btn-refresh", "Refresh", "action_refresh_list"),
    ToolbarAction("meeting-btn-delete", "Delete", "action_delete_meeting", "error"),
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
