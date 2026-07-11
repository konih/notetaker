from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import (
    Button,
    ContentSwitcher,
    DataTable,
    Input,
    Static,
    Tab,
    Tabs,
    TextArea,
)

from live_meeting_transcriber.application.container import Container
from live_meeting_transcriber.domain.models import TranscriptSegment
from live_meeting_transcriber.ui.state.model import AppState
from live_meeting_transcriber.ui.state.store import Store
from live_meeting_transcriber.ui.tui import meeting_actions, meeting_detail
from live_meeting_transcriber.ui.tui.meeting_toolbar import (
    MORE_BUTTON_ID,
    primary_toolbar_actions,
    toolbar_action_by_button_id,
)
from live_meeting_transcriber.ui.tui.people_suggesters import (
    CommaSeparatedPeopleSuggester,
    PeoplePrefixSuggester,
)
from live_meeting_transcriber.ui.tui.tab_complete_input import TabCompletableInput

# Canonical Summarize key and the summary-editor placeholder renderer live in
# meeting_detail (A5); aliased here because compose() renders the key hint and
# guard tests import the renderer from this module.
_SUMMARIZE_KEY = meeting_detail.SUMMARIZE_KEY
_format_summary_for_editor = meeting_detail.format_summary_for_editor


class MeetingFilterInput(Input):
    """The Meetings-tab filter box; Escape clears it and hands focus back (U17)."""

    class Cleared(Message):
        """Posted when the user dismisses the filter with Escape."""

    BINDINGS = [Binding("escape", "dismiss_filter", "Clear filter", show=False)]

    def action_dismiss_filter(self) -> None:
        self.post_message(self.Cleared())


class MeetingBrowser(Vertical):
    """Second tab: browse meetings, edit metadata, speakers, transcript; summarize; people autocomplete."""

    DEFAULT_CSS = """
    #meeting-toolbar { height: auto; margin-bottom: 1; }
    /* Size toolbar buttons to their labels (Textual's default Button min-width is 16)
       so the primary row — now including the promoted Speaker ID button — fits the
       120-col baseline instead of overflowing and clipping the rightmost button. */
    #meeting-toolbar Button { margin-right: 1; min-width: 8; width: auto; }
    """

    BINDINGS = [
        Binding("ctrl+s", "save_meeting", "Save meeting", show=True, priority=True),
        # No Meetings-local Summarize binding: the canonical key is the global `k`
        # (UX-OQ-3), whose action is tab-aware and summarizes the selected meeting
        # here. The old duplicate `ctrl+g` was purged in U12; the toolbar button
        # still routes to action_summarize_meeting for mouse users.
        Binding("ctrl+r", "refresh_list", "Refresh", show=True, priority=True),
        # Plain `d` (not the old ctrl+shift+d/shift+delete/ctrl+delete chord, which collapses
        # onto ctrl+d / never fires on standard terminals). Focus stays on the meetings table
        # after selecting a row, so `d` fires there; non-priority so it still types into the
        # title/notes/attendees inputs when one of them is focused. The visible red Delete
        # toolbar button is the primary affordance (U24).
        Binding("d", "delete_meeting", "Delete meeting", show=True),
        Binding("ctrl+e", "edit_segment", "Edit line", show=True, priority=True),
        # ctrl+d, not ctrl+i: terminals collapse ctrl+i onto Tab (0x09), so the old
        # binding never fired and Speaker ID was unrunnable from the keyboard here.
        Binding("ctrl+d", "finalize_selected_speakers", "Speaker ID", show=True, priority=True),
        Binding("i", "show_session_media", "Media files", show=False, priority=True),
        Binding("p", "slide_preview", "Slide preview", show=False, priority=True),
        Binding("ctrl+v", "import_video", "Import video", show=True, priority=True),
        Binding("m", "show_more_menu", "More actions", show=True, priority=True),
        # U17: `/` jumps to the filter box (non-priority so it still types into the
        # title/notes/attendees inputs when one of them is focused).
        Binding("/", "focus_filter", "Filter meetings", show=False),
    ]

    def __init__(self, *, container: Container, store: Store) -> None:
        super().__init__(id="meeting-browser")
        self.container = container
        self.store = store
        self._prefix_suggester = PeoplePrefixSuggester(container.people)
        self._comma_suggester = CommaSeparatedPeopleSuggester(container.people)
        self._selected_session_id: UUID | None = None
        self._filter_query = ""
        self._segments: list[TranscriptSegment] = []
        self._transcript_row_ids: list[str] = []
        self._speaker_keys: list[str] = []
        self._last_catalog_key: tuple[str, ...] | None = None
        self._unsub: Callable[[], None] | None = None

    @property
    def selected_session_id(self) -> UUID | None:
        return self._selected_session_id

    def compose(self) -> ComposeResult:
        # U14: the header is orientation only. The screen keeps exactly two action
        # channels — the U9 toolbar below (explicit surface) and the footer plus the
        # ? keymap overlay (fallback) — so the header no longer repeats per-action
        # key hints as a third concurrent affordance layer; it just points at ?.
        yield Static(
            "[bold]Meetings[/bold] — select a row · [dim]?[/dim] shortcuts",
            id="meeting-browser-header",
        )
        with Horizontal(id="meeting-toolbar"):
            for action in primary_toolbar_actions():
                yield Button(action.label, id=action.button_id, variant=action.variant)  # type: ignore[arg-type]
            yield Button("More…", id=MORE_BUTTON_ID)
        with Horizontal(id="meeting-browser-split"):
            with Vertical(id="meeting-list-pane"):
                yield MeetingFilterInput(
                    placeholder="/ filter — text · after:2026-01-31 · before:2026-12-24",
                    id="meeting-filter",
                )
                yield DataTable(id="meeting-sessions-table", cursor_type="row", zebra_stripes=True)
            with Vertical(id="meeting-browser-detail"):
                yield Static("No meeting selected.", id="meeting-detail-status")
                yield Tabs(
                    Tab("Overview", id="dt-overview"),
                    Tab("Transcript", id="dt-transcript"),
                    Tab("Summary", id="dt-summary"),
                    id="detail-tabs",
                )
                with ContentSwitcher(initial="detail-overview", id="detail-switcher"):
                    with VerticalScroll(id="detail-overview"):
                        yield TabCompletableInput(
                            placeholder="Title", id="meeting-title", disabled=True
                        )
                        yield Static("Notes", classes="dim")
                        yield TextArea(id="meeting-notes", disabled=True, language=None)
                        yield Static(
                            "Attendees (comma-separated; Tab completes full name when suggested)",
                            classes="dim",
                        )
                        yield TabCompletableInput(
                            placeholder="Alice, Bob, …", id="meeting-attendees", disabled=True
                        )
                        yield Static(
                            "Speaker labels → display names "
                            "(Tab completes full name when suggested)",
                            classes="dim",
                        )
                        yield Vertical(id="meeting-speaker-area")
                    with Vertical(id="detail-transcript"):
                        yield Static(
                            "Transcript (scrollable — place cursor on a line, ctrl+e to edit)",
                            classes="dim",
                        )
                        yield TextArea(id="meeting-transcript", read_only=True, language=None)
                    with Vertical(id="detail-summary"):
                        yield Static(f"AI summary ({_SUMMARIZE_KEY} to generate)", classes="dim")
                        yield TextArea(id="meeting-summary", disabled=True, language=None)

    def on_tabs_tab_activated(self, event: Tabs.TabActivated) -> None:
        """Route the detail sub-tabs (Overview / Transcript / Summary) to their pane."""
        if event.tabs.id != "detail-tabs" or event.tab is None:
            return
        pane = {
            "dt-overview": "detail-overview",
            "dt-transcript": "detail-transcript",
            "dt-summary": "detail-summary",
        }.get(event.tab.id or "")
        if pane:
            self.query_one("#detail-switcher", ContentSwitcher).current = pane

    def on_mount(self) -> None:
        st = self.query_one("#meeting-sessions-table", DataTable)
        st.add_columns(" ", "Title", "Started")
        st.border_title = "meetings"
        st.border_subtitle = "● live · ▶ video · ⏸ interrupted"
        self.query_one("#meeting-browser-detail").border_title = "detail"
        attendees = self.query_one("#meeting-attendees", TabCompletableInput)
        attendees.suggester = self._comma_suggester
        self.refresh_session_list()
        st = self.query_one("#meeting-sessions-table", DataTable)
        self.query_one("#meeting-btn-slide-preview", Button).disabled = True
        if st.row_count > 0:
            st.move_cursor(row=0)
        self._unsub = self.store.subscribe(self._on_store)

    def on_unmount(self) -> None:
        if self._unsub is not None:
            self._unsub()

    def _on_store(self, state: AppState) -> None:
        key = tuple(r.id for r in state.sessions_catalog)
        if key != self._last_catalog_key:
            self._last_catalog_key = key
            self.refresh_session_list(preserve_selection=True)

        pending = state.pending_meeting_detail_reload
        if pending is not None and self._selected_session_id == pending:

            async def _reload() -> None:
                await self._load_detail(pending)

            self.run_worker(_reload(), exclusive=True)

    def refresh_session_list(self, *, preserve_selection: bool = False) -> None:
        meeting_detail.refresh_session_list(self, preserve_selection=preserve_selection)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "meeting-filter":
            return
        self._filter_query = event.value
        self.refresh_session_list(preserve_selection=True)

    def on_meeting_filter_input_cleared(self, _event: MeetingFilterInput.Cleared) -> None:
        filter_input = self.query_one("#meeting-filter", Input)
        filter_input.value = ""  # triggers Input.Changed → refresh
        self.query_one("#meeting-sessions-table", DataTable).focus()

    def action_focus_filter(self) -> None:
        self.query_one("#meeting-filter", Input).focus()

    def select_session(self, session_id: UUID) -> None:
        """Move the cursor to ``session_id``, clearing the filter if it hides it (U11)."""
        table = self.query_one("#meeting-sessions-table", DataTable)
        key = str(session_id)

        def _row_index() -> int | None:
            for i, row_key in enumerate(table.rows):
                if row_key.value == key:
                    return i
            return None

        idx = _row_index()
        if idx is None and self._filter_query:
            self._filter_query = ""
            self.query_one("#meeting-filter", Input).value = ""
            self.refresh_session_list()
            idx = _row_index()
        if idx is not None:
            table.move_cursor(row=idx)
            table.focus()

    async def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.control.id != "meeting-sessions-table":
            return
        key = event.row_key.value
        self._selected_session_id = UUID(str(key))
        await self._load_detail(self._selected_session_id)

    async def _load_detail(self, session_id: UUID) -> None:
        await meeting_detail.load_detail(self, session_id)

    async def _clear_detail(self) -> None:
        await meeting_detail.clear_detail(self)

    # Action bodies live in meeting_actions (A5, ARCH-10). Each action_* method
    # stays here as a thin delegate so BINDINGS, the toolbar catalog
    # (dispatch_toolbar_action resolves by name on this widget), and the ? overlay
    # keep their contracts.
    async def action_import_video(self) -> None:
        await meeting_actions.import_video(self)

    async def action_save_meeting(self) -> None:
        await meeting_actions.save_meeting(self)

    async def action_finalize_selected_speakers(self) -> None:
        await meeting_actions.finalize_selected_speakers(self)

    async def action_summarize_meeting(self) -> None:
        await meeting_actions.summarize_meeting(self)

    async def action_show_session_media(self) -> None:
        await meeting_actions.show_session_media(self)

    async def action_slide_preview(self) -> None:
        await meeting_actions.slide_preview(self)

    async def action_refresh_list(self) -> None:
        await meeting_actions.refresh_list(self)

    async def action_export_meeting(self) -> None:
        await meeting_actions.export_meeting(self)

    async def action_continue_recording(self) -> None:
        await meeting_actions.continue_recording(self)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid == MORE_BUTTON_ID:
            await self.action_show_more_menu()
            return
        action = toolbar_action_by_button_id(bid)
        if action is not None:
            await self.dispatch_toolbar_action(action.action)

    async def dispatch_toolbar_action(self, action_name: str) -> None:
        """Invoke the ``MeetingBrowser`` coroutine named ``action_name``."""
        method = getattr(self, action_name, None)
        if method is not None:
            await method()

    async def action_show_more_menu(self) -> None:
        await meeting_actions.show_more_menu(self)

    async def action_delete_meeting(self) -> None:
        await meeting_actions.delete_meeting(self)

    async def action_edit_segment(self) -> None:
        await meeting_actions.edit_segment(self)
