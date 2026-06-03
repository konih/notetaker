from __future__ import annotations

import functools
import shutil
from collections.abc import Callable
from uuid import UUID

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Static, TextArea

from live_meeting_transcriber.application.container import Container
from live_meeting_transcriber.application.session_service import SessionService
from live_meeting_transcriber.domain.models import Summary, TranscriptSegment
from live_meeting_transcriber.domain.speaker_display import format_transcript_speaker_label
from live_meeting_transcriber.ui.state import actions as act
from live_meeting_transcriber.ui.state.model import AppState, RecordingStatus
from live_meeting_transcriber.ui.state.store import Store
from live_meeting_transcriber.ui.tui.people_suggesters import (
    CommaSeparatedPeopleSuggester,
    PeoplePrefixSuggester,
)
from live_meeting_transcriber.ui.tui.tab_complete_input import TabCompletableInput
from live_meeting_transcriber.utils.time import utc_now


def _format_summary_for_editor(summary: Summary | None) -> str:
    if summary is None:
        return "— No summary yet. Press ctrl+g to generate. —"
    parts: list[str] = [summary.summary_markdown.strip()]
    if summary.decisions:
        parts.append("## Decisions\n" + "\n".join(f"- {d.text}" for d in summary.decisions))
    if summary.action_items:
        parts.append(
            "## Action items\n" + "\n".join(f"- [ ] {ai.text}" for ai in summary.action_items)
        )
    return "\n\n".join(parts)


class EditSegmentModal(ModalScreen[bool | None]):
    """Edit transcript line text in SQLite."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
        Binding("ctrl+enter", "save", "Save", show=True),
    ]

    def __init__(self, *, container: Container, segment: TranscriptSegment) -> None:
        super().__init__()
        self._container = container
        self._segment_id = segment.id
        self._initial = segment.text

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("Edit segment text — Ctrl+Enter: save · Esc: cancel", classes="settings-title"),
            TextArea(text=self._initial, id="segment-edit-area", language=None),
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


class MeetingBrowser(Vertical):
    """Second tab: browse meetings, edit metadata, speakers, transcript; summarize; people autocomplete."""

    DEFAULT_CSS = """
    #meeting-toolbar { height: auto; margin-bottom: 1; }
    #meeting-toolbar Button { margin-right: 1; }
    """

    BINDINGS = [
        Binding("ctrl+s", "save_meeting", "Save meeting", show=True, priority=True),
        Binding("ctrl+g", "summarize_meeting", "Summarize", show=True, priority=True),
        Binding("ctrl+r", "refresh_list", "Refresh", show=True, priority=True),
        Binding(
            "ctrl+shift+d,shift+delete,ctrl+delete",
            "delete_meeting",
            "Delete meeting",
            show=True,
            priority=True,
            group=Binding.Group(description="Delete meeting", compact=True),
        ),
        Binding("ctrl+e", "edit_segment", "Edit line", show=True, priority=True),
        Binding("ctrl+i", "finalize_selected_speakers", "Speaker ID", show=False, priority=True),
    ]

    def __init__(self, *, container: Container, store: Store) -> None:
        super().__init__(id="meeting-browser")
        self.container = container
        self.store = store
        self._prefix_suggester = PeoplePrefixSuggester(container.people)
        self._comma_suggester = CommaSeparatedPeopleSuggester(container.people)
        self._selected_session_id: UUID | None = None
        self._segments: list[TranscriptSegment] = []
        self._transcript_row_ids: list[str] = []
        self._speaker_keys: list[str] = []
        self._last_catalog_key: tuple[str, ...] | None = None
        self._unsub: Callable[[], None] | None = None

    @property
    def selected_session_id(self) -> UUID | None:
        return self._selected_session_id

    def compose(self) -> ComposeResult:
        yield Static(
            "[bold]Meetings[/bold] — select a row · [dim]Continue recording[/dim] appends to the open meeting · "
            "use buttons or [dim]w[/dim] export · [dim]k[/dim] summarize · [dim]ctrl+i[/dim] speaker ID · "
            "[dim]ctrl+s[/dim] save · [dim]ctrl+g[/dim] summarize · [dim]ctrl+e[/dim] edit line · "
            "shift+del / ctrl+shift+d delete · [dim]ctrl+r[/dim] refresh",
            id="meeting-browser-header",
        )
        with Horizontal(id="meeting-toolbar"):
            yield Button("Save", id="meeting-btn-save", variant="primary")
            yield Button("Continue recording", id="meeting-btn-continue-record")
            yield Button("Summarize", id="meeting-btn-summarize")
            yield Button("Speaker ID", id="meeting-btn-speaker-id", variant="success")
            yield Button("Export markdown", id="meeting-btn-export")
            yield Button("Refresh", id="meeting-btn-refresh")
            yield Button("Edit line", id="meeting-btn-edit-line")
            yield Button("Delete", id="meeting-btn-delete", variant="error")
        with Horizontal(id="meeting-browser-split"):
            yield DataTable(id="meeting-sessions-table", cursor_type="row", zebra_stripes=True)
            with Vertical(id="meeting-browser-detail"):
                yield Static("No meeting selected.", id="meeting-detail-status")
                yield TabCompletableInput(placeholder="Title", id="meeting-title", disabled=True)
                yield Static("Notes", classes="dim")
                yield TextArea(id="meeting-notes", disabled=True, language=None)
                yield Static("AI summary (ctrl+g to generate)", classes="dim")
                yield TextArea(id="meeting-summary", disabled=True, language=None)
                yield Static(
                    "Attendees (comma-separated; Tab completes full name when suggested)",
                    classes="dim",
                )
                yield TabCompletableInput(
                    placeholder="Alice, Bob, …", id="meeting-attendees", disabled=True
                )
                yield Static(
                    "Speaker labels → display names (Tab completes full name when suggested)",
                    classes="dim",
                )
                yield Vertical(id="meeting-speaker-area")
                yield Static("Transcript", classes="dim")
                yield DataTable(
                    id="meeting-transcript-table", cursor_type="row", zebra_stripes=True
                )

    def on_mount(self) -> None:
        st = self.query_one("#meeting-sessions-table", DataTable)
        st.add_columns("Title", "Started (UTC)", "Session")
        tt = self.query_one("#meeting-transcript-table", DataTable)
        tt.add_columns("Time", "Speaker", "Text")
        attendees = self.query_one("#meeting-attendees", TabCompletableInput)
        attendees.suggester = self._comma_suggester
        self.refresh_session_list()
        st = self.query_one("#meeting-sessions-table", DataTable)
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
        table = self.query_one("#meeting-sessions-table", DataTable)
        selected = (
            str(self._selected_session_id)
            if preserve_selection and self._selected_session_id
            else None
        )
        table.clear()
        for s in self.container.sessions.list():
            short = str(s.id)[:8] + "…"
            table.add_row(
                s.title[:44] + ("…" if len(s.title) > 44 else ""),
                s.started_at.isoformat(timespec="seconds"),
                short,
                key=str(s.id),
            )
        if selected:
            for i, s in enumerate(self.container.sessions.list()):
                if str(s.id) == selected:
                    table.move_cursor(row=i)
                    break

    async def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.control.id != "meeting-sessions-table":
            return
        key = event.row_key.value
        self._selected_session_id = UUID(str(key))
        await self._load_detail(self._selected_session_id)

    async def _load_detail(self, session_id: UUID) -> None:
        session = self.container.sessions.get(session_id)
        if session is None:
            return
        status = self.query_one("#meeting-detail-status", Static)
        status.update(f"Editing [bold]{session.title}[/bold] ({session_id})")

        title_inp = self.query_one("#meeting-title", TabCompletableInput)
        title_inp.disabled = False
        title_inp.value = session.title

        notes = self.query_one("#meeting-notes", TextArea)
        notes.disabled = False
        notes.text = session.notes

        att = self.query_one("#meeting-attendees", TabCompletableInput)
        att.disabled = False
        att.value = ", ".join(session.attendees)
        att.suggester = self._comma_suggester

        summary = self.container.summaries.get_by_session(session_id)
        sum_ta = self.query_one("#meeting-summary", TextArea)
        sum_ta.disabled = False
        sum_ta.text = _format_summary_for_editor(summary)
        sum_ta.disabled = True

        self._segments = self.container.transcripts.list_by_session(session_id)
        name_map = self.container.session_speakers.get_map(session_id)
        self._speaker_keys = sorted({s.speaker for s in self._segments})

        spk_area = self.query_one("#meeting-speaker-area", Vertical)
        await spk_area.remove_children()
        rows: list[Horizontal] = []
        for sk in self._speaker_keys:
            rows.append(
                Horizontal(
                    Static(f"{sk} →", classes="spk-label"),
                    TabCompletableInput(
                        value=name_map.get(sk, ""),
                        placeholder="Display name",
                        suggester=self._prefix_suggester,
                        id=f"spk-{sk}",
                        classes="spk-inp",
                    ),
                    classes="spk-row",
                )
            )
        if rows:
            await spk_area.mount(*rows)

        tt = self.query_one("#meeting-transcript-table", DataTable)
        tt.clear()
        self._transcript_row_ids = []
        for s in self._segments:
            label = format_transcript_speaker_label(s.speaker, name_map)
            snippet = s.text.replace("\n", " ")
            if len(snippet) > 100:
                snippet = snippet[:97] + "…"
            tt.add_row(
                s.started_at.isoformat(timespec="minutes"),
                label,
                snippet,
                key=str(s.id),
            )
            self._transcript_row_ids.append(str(s.id))

        st = self.store.get_state()
        if st.pending_meeting_detail_reload == session_id:
            self.store.dispatch(act.DetailReloadAcknowledged(at=utc_now()))

    async def _clear_detail(self) -> None:
        self._selected_session_id = None
        self._segments = []
        self._transcript_row_ids = []
        self._speaker_keys = []
        self.query_one("#meeting-detail-status", Static).update("No meeting selected.")
        self.query_one("#meeting-title", TabCompletableInput).value = ""
        self.query_one("#meeting-title", TabCompletableInput).disabled = True
        notes = self.query_one("#meeting-notes", TextArea)
        notes.text = ""
        notes.disabled = True
        sum_ta = self.query_one("#meeting-summary", TextArea)
        sum_ta.text = ""
        sum_ta.disabled = True
        att = self.query_one("#meeting-attendees", TabCompletableInput)
        att.value = ""
        att.disabled = True
        spk_area = self.query_one("#meeting-speaker-area", Vertical)
        await spk_area.remove_children()
        self.query_one("#meeting-transcript-table", DataTable).clear()

    async def action_save_meeting(self) -> None:
        if self._selected_session_id is None:
            self.app.notify("Select a meeting first.", severity="warning")
            return
        sid = self._selected_session_id
        title = self.query_one("#meeting-title", TabCompletableInput).value.strip()
        notes = self.query_one("#meeting-notes", TextArea).text
        raw_att = self.query_one("#meeting-attendees", TabCompletableInput).value
        parts = [p.strip() for p in raw_att.replace("\n", ",").split(",")]
        attendees = [p for p in parts if p]

        if not title:
            self.app.notify("Title required.", severity="error")
            return

        updated = self.container.sessions.update_details(
            sid, title=title, notes=notes, attendees=attendees
        )
        if updated is None:
            self.app.notify("Save failed.", severity="error")
            return

        mapping: dict[str, str] = {}
        for sk in self._speaker_keys:
            inp = self.query_one(f"#spk-{sk}", TabCompletableInput)
            mapping[sk] = inp.value.strip()
        self.container.session_speakers.replace_map(sid, mapping)

        for name in attendees:
            self.container.people.touch(name)
        for v in mapping.values():
            if v:
                self.container.people.touch(v)

        await self.store.dispatch_with_effects(act.SessionsRefreshRequested(at=utc_now()))
        self.app.notify("Meeting saved (title, notes, attendees, speakers).")
        self.refresh_session_list(preserve_selection=True)

    async def action_finalize_selected_speakers(self) -> None:
        if self._selected_session_id is None:
            self.app.notify("Select a meeting first.", severity="warning")
            return
        sid = self._selected_session_id
        self.app.notify("Running speaker ID (WhisperX) — this may take a while…", severity="information")
        await self.store.dispatch_with_effects(act.FinalizeSessionRequested(session_id=sid, at=utc_now()))

    async def action_summarize_meeting(self) -> None:
        if self._selected_session_id is None:
            self.app.notify("Select a meeting first.", severity="warning")
            return
        sid = self._selected_session_id
        self.app.notify("Summarizing… (OpenAI)")
        svc = SessionService(
            sessions=self.container.sessions,
            transcripts=self.container.transcripts,
            summaries=self.container.summaries,
            summarizer=self.container.summarizer,
            session_speakers=self.container.session_speakers,
        )
        try:
            await svc.summarize_session(session_id=sid)
        except Exception as e:
            self.app.notify(f"Summarize failed: {e}", severity="error")
            return
        self.app.notify("Summary saved.")
        await self.store.dispatch_with_effects(act.SessionsRefreshRequested(at=utc_now()))
        await self._load_detail(sid)

    async def action_refresh_list(self) -> None:
        self.refresh_session_list(preserve_selection=True)
        if self._selected_session_id is not None:
            await self._load_detail(self._selected_session_id)
        self.app.notify("Refreshed.")

    async def action_export_meeting(self) -> None:
        if self._selected_session_id is None:
            self.app.notify("Select a meeting first.", severity="warning")
            return
        await self.store.dispatch_with_effects(
            act.ExportMarkdownRequested(at=utc_now(), session_id=self._selected_session_id)
        )

    async def action_continue_recording(self) -> None:
        if self._selected_session_id is None:
            self.app.notify("Select a meeting in the list first.", severity="warning")
            return
        st = self.store.get_state()
        if st.recording_status in (
            RecordingStatus.starting,
            RecordingStatus.recording,
            RecordingStatus.stopping,
        ):
            self.app.notify(
                "Stop the current recording before continuing another meeting.", severity="warning"
            )
            return
        session = self.container.sessions.get(self._selected_session_id)
        if session is None:
            self.app.notify("Meeting not found in the database.", severity="error")
            return
        await self.store.dispatch_with_effects(
            act.RecordingStartRequested(
                title=session.title,
                audio_source=st.audio_source,
                at=utc_now(),
                resume_session_id=session.id,
            )
        )
        self.app.notify(
            f"Recording into: {session.title}. Switch to the Live tab for the transcript."
        )
        focus = getattr(self.app, "action_focus_live_tab", None)
        if callable(focus):
            focus()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid == "meeting-btn-save":
            await self.action_save_meeting()
        elif bid == "meeting-btn-continue-record":
            await self.action_continue_recording()
        elif bid == "meeting-btn-summarize":
            await self.action_summarize_meeting()
        elif bid == "meeting-btn-speaker-id":
            await self.action_finalize_selected_speakers()
        elif bid == "meeting-btn-export":
            await self.action_export_meeting()
        elif bid == "meeting-btn-refresh":
            await self.action_refresh_list()
        elif bid == "meeting-btn-edit-line":
            await self.action_edit_segment()
        elif bid == "meeting-btn-delete":
            await self.action_delete_meeting()

    async def action_delete_meeting(self) -> None:
        if self._selected_session_id is None:
            self.app.notify("Select a meeting first.", severity="warning")
            return
        sid = self._selected_session_id
        st = self.store.get_state()
        if st.current_session_id == sid and st.recording_status in (
            RecordingStatus.starting,
            RecordingStatus.recording,
            RecordingStatus.stopping,
        ):
            self.app.notify(
                "Cannot delete the meeting while recording is in progress.", severity="error"
            )
            return
        title = (
            self.query_one("#meeting-title", TabCompletableInput).value.strip()
            or str(sid)[:8] + "…"
        )
        await self.app.push_screen(
            ConfirmDeleteMeetingModal(title=title, session_id=sid),
            callback=functools.partial(self._after_delete_meeting_confirm, sid),
        )

    def _after_delete_meeting_confirm(self, sid: UUID, confirmed: bool | None) -> None:
        if not confirmed:
            return
        self.run_worker(self._complete_delete_meeting(sid), exclusive=True)

    async def _complete_delete_meeting(self, sid: UUID) -> None:
        catalog_before = self.container.sessions.list()
        try:
            del_idx = next(i for i, s in enumerate(catalog_before) if s.id == sid)
        except StopIteration:
            del_idx = 0
        removed = self.container.sessions.delete(sid)
        if removed:
            chunk_dir = self.container.settings.ensure_data_dir() / "chunks" / str(sid)
            if chunk_dir.is_dir():
                shutil.rmtree(chunk_dir, ignore_errors=True)
            self.app.notify("Meeting deleted.")
        else:
            self.app.notify("Meeting was already removed.", severity="warning")

        remaining = self.container.sessions.list()
        if remaining:
            pick = min(del_idx, len(remaining) - 1)
            self._selected_session_id = remaining[pick].id
        else:
            self._selected_session_id = None

        await self.store.dispatch_with_effects(act.SessionsRefreshRequested(at=utc_now()))
        self.refresh_session_list(preserve_selection=True)

        if self._selected_session_id is not None:
            table = self.query_one("#meeting-sessions-table", DataTable)
            for i, s in enumerate(self.container.sessions.list()):
                if s.id == self._selected_session_id:
                    table.move_cursor(row=i)
                    break
            await self._load_detail(self._selected_session_id)
        else:
            await self._clear_detail()

    async def action_edit_segment(self) -> None:
        if self._selected_session_id is None or not self._segments:
            self.app.notify("Select a meeting with transcript lines.", severity="warning")
            return
        tt = self.query_one("#meeting-transcript-table", DataTable)
        coord = tt.cursor_coordinate
        if coord is None or coord.row < 0 or coord.row >= len(self._transcript_row_ids):
            self.app.notify("Select a transcript row first.", severity="warning")
            return
        seg_id = UUID(self._transcript_row_ids[coord.row])
        seg = next((s for s in self._segments if s.id == seg_id), None)
        if seg is None:
            return
        await self.app.push_screen(
            EditSegmentModal(container=self.container, segment=seg),
            callback=self._after_edit_segment_modal,
        )

    def _after_edit_segment_modal(self, result: bool | None) -> None:
        if not result or self._selected_session_id is None:
            return
        sid = self._selected_session_id

        async def _reload() -> None:
            await self._load_detail(sid)

        self.run_worker(_reload, exclusive=True)
