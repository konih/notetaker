"""Modal dialogs used by the Meetings tab (A5, ARCH-10).

These ``ModalScreen`` subclasses are self-contained — they take their inputs via the
constructor and communicate results back with ``dismiss`` — so they live apart from the
``MeetingBrowser`` widget. Re-exported from ``meeting_browser`` for backwards-compatible
imports.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, OptionList, Static, TextArea
from textual.widgets.option_list import Option

from live_meeting_transcriber.application.container import Container
from live_meeting_transcriber.domain.models import TranscriptSegment
from live_meeting_transcriber.ui.tui.meeting_toolbar import ToolbarAction


class EditSegmentModal(ModalScreen[bool | None]):
    """Edit transcript line text in SQLite."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True, priority=True),
        Binding("ctrl+enter,ctrl+return", "save", "Save", show=True, priority=True),
    ]

    def __init__(self, *, container: Container, segment: TranscriptSegment) -> None:
        super().__init__()
        self._container = container
        self._segment_id = segment.id
        self._initial = segment.text

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("Edit segment text", classes="settings-title"),
            Static(
                "Ctrl+Enter: save · Esc: cancel — or use the buttons below.",
                classes="dim",
            ),
            TextArea(text=self._initial, id="segment-edit-area", language=None),
            Horizontal(
                Button("Save", id="segment-edit-save", variant="primary"),
                Button("Cancel", id="segment-edit-cancel"),
            ),
            classes="settings-dialog",
        )

    async def action_save(self) -> None:
        area = self.query_one("#segment-edit-area", TextArea)
        text = area.text.strip()
        if not text:
            self.app.notify("Text must not be empty.", severity="error")
            return
        updated = self._container.transcripts.update_segment_text(self._segment_id, text)
        if updated is None:
            self.app.notify("Failed to save segment.", severity="error")
            self.dismiss(None)
            return
        self.app.notify("Segment saved.")
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(None)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "segment-edit-save":
            await self.action_save()
        elif event.button.id == "segment-edit-cancel":
            self.action_cancel()


class SummaryContextModal(ModalScreen[str | None]):
    """Optional one-off LLM guidance before summarization (not persisted)."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True, priority=True),
        Binding("ctrl+enter,ctrl+return", "submit", "Summarize", show=True, priority=True),
    ]

    def __init__(self, initial: str = "") -> None:
        super().__init__()
        self._initial = initial

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("Optional context for summary", classes="settings-title"),
            Static(
                "Add focus, audience, or topics for the AI. "
                "Ctrl+Enter: summarize with text below · Esc: cancel — or use buttons.",
                classes="dim",
            ),
            TextArea(id="summary-context-area", language=None),
            Horizontal(
                Button("Summarize", id="summary-with-context", variant="primary"),
                Button("Summarize without context", id="summary-without-context"),
                Button("Cancel", id="summary-cancel"),
            ),
            classes="settings-dialog",
        )

    def on_mount(self) -> None:
        area = self.query_one("#summary-context-area", TextArea)
        if self._initial:
            area.text = self._initial
        area.focus()

    def action_submit(self) -> None:
        area = self.query_one("#summary-context-area", TextArea)
        self.dismiss(area.text.strip())

    def action_submit_without_context(self) -> None:
        self.dismiss("")

    def action_cancel(self) -> None:
        self.dismiss(None)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid == "summary-with-context":
            self.action_submit()
        elif bid == "summary-without-context":
            self.action_submit_without_context()
        elif bid == "summary-cancel":
            self.action_cancel()


class SessionMediaModal(ModalScreen[None]):
    """Read-only inventory of on-disk WAVs, slides, and exports for the selected meeting."""

    BINDINGS = [Binding("escape", "close", "Close", show=True)]

    def __init__(self, *, body: str) -> None:
        super().__init__()
        self._body = body

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("Session media on disk", classes="settings-title"),
            Static(self._body, id="session-media-body"),
            Static("[dim]Esc[/] close", classes="hint"),
            classes="settings-dialog",
        )

    def action_close(self) -> None:
        self.dismiss()


class ConfirmOverwriteExportModal(ModalScreen[bool]):
    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True, priority=True),
        Binding("y,Y", "confirm", "Yes", show=True, priority=True),
        Binding("n,N", "cancel", "No", show=True, priority=True),
    ]

    def __init__(self, *, path: Path) -> None:
        super().__init__()
        self._path = path

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("Export file already exists", classes="settings-title"),
            Static(f"[bold]{self._path}[/bold]", id="confirm-overwrite-path"),
            Static(
                "The on-disk file differs from the new export.\n\n"
                "Overwrite? [bold]Y[/bold]es · [bold]N[/bold]o · [bold]Esc[/bold] cancel",
                classes="dim",
            ),
            classes="settings-dialog",
        )

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class ConfirmDeleteMeetingModal(ModalScreen[bool]):
    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True, priority=True),
        Binding("y,Y", "confirm", "Yes", show=True, priority=True),
        Binding("n,N", "cancel", "No", show=True, priority=True),
    ]

    def __init__(self, *, title: str, session_id: UUID) -> None:
        super().__init__()
        self._title = title
        self._session_id = session_id

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("Delete this meeting?", classes="settings-title"),
            Static(f"[bold]{self._title}[/bold]", id="confirm-del-title"),
            Static(
                f"Session [dim]{self._session_id}[/dim]\n\n"
                "Removes transcript, summary, and speaker labels from the database "
                "and deletes any saved audio chunks for this session.\n\n"
                "[bold]Y[/bold]es · [bold]N[/bold]o · [bold]Esc[/bold] cancel",
                classes="dim",
            ),
            classes="settings-dialog",
        )

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class MeetingActionsMenu(ModalScreen[str | None]):
    """U9 — overflow menu for the less-common Meetings actions.

    Dismisses with the chosen action's ``MeetingBrowser`` method name, or ``None``
    when cancelled.
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True, priority=True),
    ]

    DEFAULT_CSS = """
    MeetingActionsMenu { align: center middle; }
    MeetingActionsMenu > Vertical {
        width: 44; height: auto; max-height: 80%;
        border: round $accent; background: $surface; padding: 1 2;
    }
    MeetingActionsMenu OptionList { height: auto; }
    """

    def __init__(self, actions: Sequence[ToolbarAction]) -> None:
        super().__init__()
        self._actions = list(actions)

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("[bold]More actions[/bold] — [dim]Esc to close[/dim]", classes="dim"),
            OptionList(
                *[Option(a.label, id=a.action) for a in self._actions],
                id="meeting-more-list",
            ),
        )

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)

    def action_cancel(self) -> None:
        self.dismiss(None)
