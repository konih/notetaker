from __future__ import annotations

import functools
from collections.abc import Callable
from uuid import UUID

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Static, TextArea

from live_meeting_transcriber.application.cleanup_service import purge_session_artifacts
from live_meeting_transcriber.application.container import Container
from live_meeting_transcriber.application.session_media import (
    collect_session_media,
    format_session_media_inventory,
)
from live_meeting_transcriber.application.session_service import SessionService
from live_meeting_transcriber.application.video_import_service import VideoImportProgress
from live_meeting_transcriber.domain.models import Summary, TranscriptSegment
from live_meeting_transcriber.ui.state import actions as act
from live_meeting_transcriber.ui.state.model import AppState, RecordingStatus
from live_meeting_transcriber.ui.state.store import Store
from live_meeting_transcriber.ui.tui.empty_states import MEETINGS_EMPTY_HINT
from live_meeting_transcriber.ui.tui.meeting_modals import (
    ConfirmDeleteMeetingModal,
    EditSegmentModal,
    MeetingActionsMenu,
    SessionMediaModal,
    SummaryContextModal,
)
from live_meeting_transcriber.ui.tui.meeting_session_helpers import (
    count_preview_candidates,
    count_saved_slides,
    format_meeting_row_title,
    format_session_type_label,
    format_slide_detail_note,
    list_preview_candidate_timestamps,
    session_has_slide_source,
    session_is_video_import,
)
from live_meeting_transcriber.ui.tui.meeting_toolbar import (
    MORE_BUTTON_ID,
    overflow_toolbar_actions,
    primary_toolbar_actions,
    toolbar_action_by_button_id,
)
from live_meeting_transcriber.ui.tui.people_suggesters import (
    CommaSeparatedPeopleSuggester,
    PeoplePrefixSuggester,
)
from live_meeting_transcriber.ui.tui.slide_preview_screen import SlidePreviewScreen
from live_meeting_transcriber.ui.tui.tab_complete_input import TabCompletableInput
from live_meeting_transcriber.ui.tui.transcript_display import format_meeting_transcript_text
from live_meeting_transcriber.ui.tui.video_import_modal import (
    VideoImportForm,
    VideoImportModal,
    format_video_import_error,
    run_video_import,
)
from live_meeting_transcriber.utils.time import format_local_datetime, utc_now


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
        Binding("ctrl+g", "summarize_meeting", "Summarize", show=True, priority=True),
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
            "[bold]Meetings[/bold] — select a row · [dim]ctrl+s[/dim] save · "
            "[dim]ctrl+g[/dim] summarize · [dim]ctrl+e[/dim] edit line · "
            "[dim]m[/dim] more actions",
            id="meeting-browser-header",
        )
        with Horizontal(id="meeting-toolbar"):
            for action in primary_toolbar_actions():
                yield Button(action.label, id=action.button_id, variant=action.variant)  # type: ignore[arg-type]
            yield Button("More…", id=MORE_BUTTON_ID)
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
                yield Static(
                    "Transcript (scrollable — place cursor on a line, ctrl+e to edit)",
                    classes="dim",
                )
                yield TextArea(id="meeting-transcript", read_only=True, language=None)

    def on_mount(self) -> None:
        st = self.query_one("#meeting-sessions-table", DataTable)
        st.add_columns("Type", "Title", "Started")
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
        table = self.query_one("#meeting-sessions-table", DataTable)
        selected = (
            str(self._selected_session_id)
            if preserve_selection and self._selected_session_id
            else None
        )
        data_dir = self.container.settings.ensure_data_dir()
        active_session_id = self.store.get_state().current_session_id
        table.clear()
        for s in self.container.sessions.list():
            is_video = session_is_video_import(data_dir, s.id)
            table.add_row(
                format_session_type_label(is_video=is_video),
                format_meeting_row_title(s, active_session_id=active_session_id),
                format_local_datetime(s.started_at),
                key=str(s.id),
            )
        if selected:
            for i, s in enumerate(self.container.sessions.list()):
                if str(s.id) == selected:
                    table.move_cursor(row=i)
                    break
        # First-run/empty state: no meetings → guide the user instead of leaving the
        # detail pane showing a bare "No meeting selected." (U10). A row selection
        # overwrites this via _load_detail.
        if table.row_count == 0:
            self.query_one("#meeting-detail-status", Static).update(MEETINGS_EMPTY_HINT)

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
        data_dir = self.container.settings.ensure_data_dir()
        is_video = session_is_video_import(data_dir, session_id)
        has_slide_source = session_has_slide_source(data_dir, session_id)
        saved_slides = count_saved_slides(data_dir, session_id)
        preview_count = count_preview_candidates(data_dir, session_id)
        preview_timestamps = list_preview_candidate_timestamps(data_dir, session_id)
        kind = "[cyan]Video import[/]" if is_video else "[green]Live recording[/]"
        slide_note = format_slide_detail_note(
            saved_slides=saved_slides,
            preview_count=preview_count,
            preview_timestamps=preview_timestamps,
            has_slide_source=has_slide_source,
        )
        status.update(f"Editing {kind} [bold]{session.title}[/bold] ({session_id}){slide_note}")

        continue_btn = self.query_one("#meeting-btn-continue-record", Button)
        continue_btn.disabled = is_video
        slide_btn = self.query_one("#meeting-btn-slide-preview", Button)
        slide_btn.disabled = not has_slide_source

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

        transcript = self.query_one("#meeting-transcript", TextArea)
        transcript.text = format_meeting_transcript_text(self._segments, session, name_map)
        self._transcript_row_ids = [str(s.id) for s in self._segments]

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
        self.query_one("#meeting-transcript", TextArea).text = ""
        continue_btn = self.query_one("#meeting-btn-continue-record", Button)
        continue_btn.disabled = False
        slide_btn = self.query_one("#meeting-btn-slide-preview", Button)
        slide_btn.disabled = True

    async def action_import_video(self) -> None:
        await self.app.push_screen(
            VideoImportModal(),
            callback=self._after_video_import_modal,
        )

    def _after_video_import_modal(self, form: VideoImportForm | None) -> None:
        if form is None:
            return
        self.run_worker(self._run_video_import(form), exclusive=True, group="video-import")

    async def _run_video_import(self, form: VideoImportForm) -> None:
        status = self.query_one("#meeting-detail-status", Static)
        status.update("[dim]Importing video…[/]")
        slide_btn = self.query_one("#meeting-btn-slide-preview", Button)
        slide_btn.disabled = True
        self.app.notify(
            f"Importing video from {form.source[:64]}{'…' if len(form.source) > 64 else ''}…",
            severity="information",
        )

        def _on_progress(p: VideoImportProgress) -> None:
            if p.phase == "slides":
                status.update("[dim]Importing — detecting slides…[/]")
                self.app.notify("Detecting slides…", severity="information", timeout=3)
                return
            pct = int(100 * p.chunk_index / p.chunk_total) if p.chunk_total else 0
            status.update(
                f"[dim]Importing — transcribing chunk {p.chunk_index}/{p.chunk_total} ({pct}%)…[/]"
            )
            self.app.notify(
                f"Transcribing chunk {p.chunk_index}/{p.chunk_total} ({pct}%) — "
                f"{p.segments_so_far} segment(s) so far",
                severity="information",
                timeout=4,
            )

        try:
            result = await run_video_import(
                self.container,
                source=form.source,
                title=form.title,
                on_progress=_on_progress,
            )
        except Exception as e:
            self.app.notify(format_video_import_error(e), severity="error", timeout=8)
            return

        await self.store.dispatch_with_effects(act.SessionsRefreshRequested(at=utc_now()))
        self._selected_session_id = result.session_id
        self.refresh_session_list(preserve_selection=True)
        table = self.query_one("#meeting-sessions-table", DataTable)
        for i, s in enumerate(self.container.sessions.list()):
            if s.id == result.session_id:
                table.move_cursor(row=i)
                break
        await self._load_detail(result.session_id)
        session = self.container.sessions.get(result.session_id)
        title = session.title if session is not None else "video"
        msg = (
            f"Imported “{title}” — {result.segment_count} segment(s). "
            "Press [bold]p[/] for slide preview."
        )
        if result.transcription is not None:
            warning = result.transcription.status_message()
            if warning is not None and result.transcription.segments > 0:
                self.app.notify(warning, severity="warning", timeout=10)
        self.app.notify(msg, timeout=6)

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
        self.app.notify(
            "Running speaker ID (WhisperX) — this may take a while…", severity="information"
        )
        await self.store.dispatch_with_effects(
            act.FinalizeSessionRequested(session_id=sid, at=utc_now())
        )

    async def action_summarize_meeting(self) -> None:
        if self._selected_session_id is None:
            self.app.notify("Select a meeting first.", severity="warning")
            return
        sid = self._selected_session_id
        await self.app.push_screen(
            SummaryContextModal(),
            callback=functools.partial(self._after_summary_context_modal, sid),
        )

    def _after_summary_context_modal(self, sid: UUID, context: str | None) -> None:
        if context is None:
            return
        user_ctx = context or None
        self.run_worker(self._run_summarize(sid, user_ctx), exclusive=True)

    async def _run_summarize(self, sid: UUID, user_context: str | None) -> None:
        self.app.notify("Summarizing… (OpenAI)")
        svc = SessionService(
            sessions=self.container.sessions,
            transcripts=self.container.transcripts,
            summaries=self.container.summaries,
            summarizer=self.container.summarizer,
            session_speakers=self.container.session_speakers,
        )
        try:
            await svc.summarize_session(session_id=sid, user_context=user_context)
        except Exception as e:
            self.app.notify(f"Summarize failed: {e}", severity="error")
            return
        self.app.notify("Summary saved.")
        await self.store.dispatch_with_effects(act.SessionsRefreshRequested(at=utc_now()))
        await self._load_detail(sid)

    async def action_show_session_media(self) -> None:
        if self._selected_session_id is None:
            self.app.notify("Select a meeting first.", severity="warning")
            return
        data_dir = self.container.settings.ensure_data_dir()
        inventory = collect_session_media(data_dir, self._selected_session_id)
        body = format_session_media_inventory(inventory)
        await self.app.push_screen(SessionMediaModal(body=body))

    async def action_slide_preview(self) -> None:
        if self._selected_session_id is None:
            self.app.notify("Select a meeting first.", severity="warning")
            return
        data_dir = self.container.settings.ensure_data_dir()
        if not session_has_slide_source(data_dir, self._selected_session_id):
            self.app.notify(
                "Slide preview needs a session with source video on disk "
                "(import with ctrl+v or transcribe-video).",
                severity="warning",
            )
            return
        await self.app.push_screen(
            SlidePreviewScreen(
                container=self.container,
                session_id=self._selected_session_id,
            ),
            callback=self._after_slide_preview,
        )

    def _after_slide_preview(self, _result: None) -> None:
        if self._selected_session_id is None:
            return
        sid = self._selected_session_id
        data_dir = self.container.settings.ensure_data_dir()
        saved = count_saved_slides(data_dir, sid)
        preview_count = count_preview_candidates(data_dir, sid)

        async def _reload() -> None:
            await self._load_detail(sid)
            if preview_count and saved == 0:
                self.app.notify(
                    "Preview complete — use [bold]Apply all candidates[/] or mark rows with "
                    "[bold]y[/] then [bold]Apply kept slides[/] in slide preview.",
                    severity="information",
                    timeout=8,
                )
            elif saved:
                self.app.notify(
                    f"{saved} slide(s) saved — ready to export with [bold]w[/].",
                    severity="information",
                    timeout=6,
                )

        self.run_worker(_reload(), exclusive=True)

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
        await self.app.push_screen(
            MeetingActionsMenu(overflow_toolbar_actions()),
            callback=self._after_more_menu,
        )

    def _after_more_menu(self, action_name: str | None) -> None:
        if action_name is None:
            return
        self.run_worker(self.dispatch_toolbar_action(action_name))

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
            purge_session_artifacts(
                self.container.settings.ensure_data_dir(),
                sid,
                dry_run=False,
            )
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
        transcript = self.query_one("#meeting-transcript", TextArea)
        row = transcript.cursor_location[0]
        if row < 0 or row >= len(self._transcript_row_ids):
            self.app.notify("Place the cursor on a transcript line first.", severity="warning")
            return
        seg_id = UUID(self._transcript_row_ids[row])
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

        self.run_worker(_reload(), exclusive=True)
