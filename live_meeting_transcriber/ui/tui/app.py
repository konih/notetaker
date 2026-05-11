from __future__ import annotations

import functools
import shutil
from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from rich.console import Group
from rich.panel import Panel
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Input,
    RichLog,
    Static,
    TabbedContent,
    TabPane,
)

from live_meeting_transcriber.application.container import (
    Container,
    ProviderSelectionError,
    build_container,
)
from live_meeting_transcriber.config.settings import Settings, load_settings
from live_meeting_transcriber.observability.logging import configure_logging
from live_meeting_transcriber.ui.effects.controller import TuiController
from live_meeting_transcriber.ui.state import actions as act
from live_meeting_transcriber.ui.state.model import AppState, RecordingStatus, TranscriptLineState
from live_meeting_transcriber.ui.state.selectors import (
    select_display_speaker,
    select_header_title,
    select_level_bar,
    select_status_line,
    select_unacknowledged_errors,
)
from live_meeting_transcriber.ui.state.store import Store
from live_meeting_transcriber.ui.tui.meeting_browser import (
    ConfirmDeleteMeetingModal,
    MeetingBrowser,
)
from live_meeting_transcriber.utils.time import utc_now


class SettingsScreen(ModalScreen[None]):
    """Read-only settings overview (values come from store only)."""

    BINDINGS = [Binding("escape", "close", "Close", show=True)]

    def compose(self) -> ComposeResult:
        app = self.app
        assert isinstance(app, TranscriberApp)
        s = app.store.get_state()
        lines = [
            f"Transcription: {s.transcription_provider} / {s.transcription_model}",
            f"Summarization: {s.summarization_provider} / {s.summary_model}",
            f"Database: {s.database_url}",
            f"Log file: {s.log_file_path or '—'}",
            f"Audio chunk (s): {s.chunk_seconds}  rate: {s.audio_sample_rate}  ch: {s.audio_channels}",
            f"Diarization: enabled={s.diarization_enabled} provider={s.diarization_provider}",
            f"Mic mix: {'on' if s.audio_include_microphone else 'off'}",
        ]
        yield Vertical(
            Static("Settings (read-only)", classes="settings-title"),
            Static("\n".join(lines), id="settings-body"),
            classes="settings-dialog",
        )

    def action_close(self) -> None:
        app = self.app
        assert isinstance(app, TranscriberApp)
        app.store.dispatch(act.SettingsScreenClosed(at=utc_now()))
        self.dismiss()


class EditSessionTitleScreen(ModalScreen[None]):
    """Rename a stored session (SQLite)."""

    BINDINGS = [Binding("escape", "cancel", "Cancel", show=True)]

    def __init__(self, session_id: str, current_title: str) -> None:
        super().__init__()
        self.session_id = session_id
        self.current_title = current_title

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("Edit session title", classes="settings-title"),
            Static("Enter: save   Esc: cancel"),
            Input(value=self.current_title, id="title-input"),
            classes="settings-dialog",
        )

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        app = self.app
        assert isinstance(app, TranscriberApp)
        title = event.value.strip()
        if not title:
            return
        await app.store.dispatch_with_effects(
            act.SessionTitleCommitRequested(
                session_id=UUID(self.session_id),
                new_title=title,
                at=utc_now(),
            )
        )
        self.dismiss()

    def action_cancel(self) -> None:
        self.dismiss()


class SessionsScreen(ModalScreen[None]):
    """Browse and rename sessions from the local database."""

    BINDINGS = [
        Binding("escape", "close", "Close", show=True),
        Binding("r", "refresh", "Refresh", show=True),
        Binding("e", "edit_title", "Edit title", show=True),
        Binding("d", "delete_selected", "Delete", show=True, priority=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._row_ids: list[str] = []
        self._unsub: Callable[[], None] | None = None

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("Sessions (local SQLite)", classes="settings-title"),
            DataTable(id="sessions-table", cursor_type="row", zebra_stripes=True),
            Static(
                "r: refresh   e: rename   d: delete selected   esc: close",
                classes="hint",
            ),
            classes="settings-dialog",
        )

    def on_mount(self) -> None:
        app = self.app
        assert isinstance(app, TranscriberApp)
        table = self.query_one("#sessions-table", DataTable)
        table.add_columns("Title", "Started (UTC)", "Ended (UTC)", "Id")
        self._unsub = app.store.subscribe(self._on_store)
        self._on_store(app.store.get_state())

    def on_unmount(self) -> None:
        if self._unsub is not None:
            self._unsub()

    def _on_store(self, state: AppState) -> None:
        table = self.query_one("#sessions-table", DataTable)
        table.clear()
        self._row_ids.clear()
        for row in state.sessions_catalog:
            self._row_ids.append(row.id)
            ended = row.ended_at.isoformat(timespec="seconds") if row.ended_at else "—"
            table.add_row(
                row.title[:56] + ("…" if len(row.title) > 56 else ""),
                row.started_at.isoformat(timespec="seconds"),
                ended,
                row.id[:8] + "…",
                key=row.id,
            )

    async def action_refresh(self) -> None:
        app = self.app
        assert isinstance(app, TranscriberApp)
        await app.store.dispatch_with_effects(act.SessionsRefreshRequested(at=utc_now()))

    async def action_edit_title(self) -> None:
        table = self.query_one("#sessions-table", DataTable)
        coord = table.cursor_coordinate
        if coord is None or coord.row < 0 or coord.row >= len(self._row_ids):
            return
        sid = self._row_ids[coord.row]
        app = self.app
        assert isinstance(app, TranscriberApp)
        row = next((r for r in app.store.get_state().sessions_catalog if r.id == sid), None)
        if row is None:
            return
        self.app.push_screen(EditSessionTitleScreen(sid, row.title))

    async def action_delete_selected(self) -> None:
        table = self.query_one("#sessions-table", DataTable)
        coord = table.cursor_coordinate
        if coord is None or coord.row < 0 or coord.row >= len(self._row_ids):
            self.app.notify("Select a session row first.", severity="warning")
            return
        sid_str = self._row_ids[coord.row]
        sid = UUID(sid_str)
        app = self.app
        assert isinstance(app, TranscriberApp)
        st = app.store.get_state()
        if st.current_session_id == sid and st.recording_status in (
            RecordingStatus.starting,
            RecordingStatus.recording,
            RecordingStatus.stopping,
        ):
            self.app.notify(
                "Cannot delete the session while recording is in progress.", severity="error"
            )
            return
        row = next((r for r in st.sessions_catalog if r.id == sid_str), None)
        title = (row.title.strip() if row else "") or sid_str[:8] + "…"
        await self.app.push_screen(
            ConfirmDeleteMeetingModal(title=title, session_id=sid),
            callback=functools.partial(self._after_sessions_delete_confirm, sid),
        )

    def _after_sessions_delete_confirm(self, sid: UUID, confirmed: bool | None) -> None:
        if not confirmed:
            return
        self.run_worker(self._execute_sessions_delete(sid), exclusive=True)

    async def _execute_sessions_delete(self, sid: UUID) -> None:
        app = self.app
        assert isinstance(app, TranscriberApp)
        removed = app.container.sessions.delete(sid)
        if removed:
            chunk_dir = app.container.settings.ensure_data_dir() / "chunks" / str(sid)
            if chunk_dir.is_dir():
                shutil.rmtree(chunk_dir, ignore_errors=True)
            self.app.notify("Session deleted.")
        else:
            self.app.notify("Session was already removed.", severity="warning")
        await app.store.dispatch_with_effects(act.SessionsRefreshRequested(at=utc_now()))

    def action_close(self) -> None:
        app = self.app
        assert isinstance(app, TranscriberApp)
        app.store.dispatch(act.SessionsScreenClosed(at=utc_now()))
        self.dismiss()


class TranscriberApp(App[None]):
    """Textual front-end: renders from Store state only."""

    TITLE = "live-meeting-transcriber"
    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("r", "record", "Record", show=True),
        Binding("x", "stop", "Stop", show=True),
        Binding("w", "export_md", "Export", show=True, priority=True),
        Binding("k", "summarize", "Summarize", show=True, priority=True),
        Binding("s", "settings", "Settings", show=True),
        Binding("m", "sessions", "Sessions", show=True),
        Binding("c", "ack_errors", "Ack errors", show=True),
        Binding("ctrl+1", "focus_live_tab", "Live tab", show=True),
        Binding("ctrl+2", "focus_meetings_tab", "Meetings tab", show=True),
    ]

    CSS = """
    TabbedContent { height: 1fr; }
    TabPane { height: 1fr; }
    #tab-live #main-row { height: 1fr; }
    #sidebar { width: 38; min-width: 38; border: solid $primary; }
    #transcript { border: solid $accent; min-width: 40; }
    #status { height: auto; padding: 0 1; }
    #notices { height: auto; padding: 0 1; border-top: solid $boost; text-style: italic; color: $success; }
    #errors { height: 1fr; padding: 0 1; border-top: solid $boost; }
    #meeting-browser { height: 1fr; }
    #meeting-browser-split { height: 1fr; min-height: 8; }
    #meeting-sessions-table { width: 38; min-width: 28; }
    #meeting-browser-detail { height: 1fr; min-height: 8; }
    #meeting-notes { height: 7; min-height: 4; max-height: 12; }
    #meeting-summary { height: 10; min-height: 5; max-height: 18; }
    #meeting-transcript-table { height: 1fr; min-height: 6; }
    .spk-row { height: auto; margin-bottom: 1; }
    .spk-label { width: 14; }
    .dim { text-style: dim; }
    .settings-dialog { padding: 1 2; width: 90; height: auto; max-height: 90%; background: $surface; border: thick $accent; }
    .settings-title { text-style: bold; }
    .hint { padding-top: 1; text-style: dim; }
    #sessions-table { height: 20; min-height: 8; }
    """

    def __init__(self, *, store: Store, container: Container) -> None:
        super().__init__()
        self.store = store
        self.container = container
        self._last_segment_keys: tuple[tuple[str, str, str], ...] | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(initial="tab-live"):
            with TabPane("Live", id="tab-live"), Horizontal(id="main-row"):
                with Vertical(id="sidebar"):
                    yield Static("", id="status")
                    yield Static("", id="notices")
                    yield Static("", id="errors")
                yield RichLog(id="transcript", highlight=True, markup=True)
            with TabPane("Meetings", id="tab-meetings"):
                yield MeetingBrowser(container=self.container, store=self.store)
        yield Footer()

    def action_focus_live_tab(self) -> None:
        self.query_one(TabbedContent).active = "tab-live"

    def action_focus_meetings_tab(self) -> None:
        self.query_one(TabbedContent).active = "tab-meetings"

    async def on_mount(self) -> None:
        self.store.subscribe(self._on_state)
        await self.store.dispatch_with_effects(act.AppStarted(at=utc_now()))

    def _on_state(self, state: AppState) -> None:
        self.sub_title = select_header_title(state)
        status = self.query_one("#status", Static)
        notices = self.query_one("#notices", Static)
        err_panel = self.query_one("#errors", Static)
        log = self.query_one("#transcript", RichLog)

        status.update(self._render_status(state))
        if state.notices:
            notices.update(
                Text.from_markup(
                    "[bold]Last actions[/]\n" + "\n".join(f"• {n}" for n in state.notices[-4:])
                )
            )
        else:
            notices.update(Text.from_markup("[dim]w: export markdown · k: summarize[/]"))
        err_panel.update(self._render_errors(state))

        def _seg_key(seg: TranscriptLineState) -> tuple[str, str, str]:
            return (seg.id, seg.speaker, seg.text)

        new_keys = tuple(_seg_key(s) for s in state.recent_transcript_segments)
        old_keys = self._last_segment_keys

        if (
            old_keys is not None
            and len(new_keys) > len(old_keys)
            and new_keys[: len(old_keys)] == old_keys
        ):
            for line in state.recent_transcript_segments[len(old_keys) :]:
                sp = select_display_speaker(state, line.speaker)
                ts = f"{line.started_at.isoformat()} → {line.ended_at.isoformat()}"
                log.write(Text.from_markup(f"[dim]{ts}[/] [bold]{sp}[/]\n{line.text}"))
        elif old_keys != new_keys:
            log.clear()
            for line in state.recent_transcript_segments:
                sp = select_display_speaker(state, line.speaker)
                ts = f"{line.started_at.isoformat()} → {line.ended_at.isoformat()}"
                log.write(Text.from_markup(f"[dim]{ts}[/] [bold]{sp}[/]\n{line.text}"))
        self._last_segment_keys = new_keys

    def _render_status(self, state: AppState) -> Group:
        log_hint = (
            state.log_file_path[:52] + "…" if len(state.log_file_path) > 55 else state.log_file_path
        )
        peak_pct = (
            f"{state.current_level_meter * 100:.0f}%"
            if state.current_level_meter is not None
            else "—"
        )
        lines = [
            f"[bold]Session[/] {state.current_session_id or '—'}",
            f"[bold]Title[/] {state.session_title or '—'}",
            f"[bold]Status[/] {select_status_line(state)}",
            f"[bold]Level[/] [{select_level_bar(state)}] {peak_pct} [dim](per chunk)[/]",
            f"[bold]Chunk[/] {state.chunk_seconds}s",
            f"[bold]Mic[/] {state.microphone_source or ('—' if not state.audio_include_microphone else 'none (monitor only)')}",
            f"[bold]Log[/] {log_hint or '—'}",
            f"[bold]Sessions[/] {len(state.sessions_catalog)} in DB"
            + (" (loading…)" if state.sessions_loading else ""),
            f"[bold]Diarization[/] provider={state.diarization_provider}"
            + (
                f" · seen: {', '.join(sorted(state.diarization_detected_speakers))}"
                if state.diarization_detected_speakers
                else ""
            ),
        ]
        return Group(*[Text.from_markup(x) for x in lines])

    def _render_errors(self, state: AppState) -> Panel:
        unacked = select_unacknowledged_errors(state)
        if not unacked and not state.warnings:
            return Panel(Text("No errors."), title="Errors & warnings", border_style="green")
        parts: list[str] = []
        for e in unacked[-8:]:
            parts.append(f"• [{e.at.isoformat()}] {e.message}")
        for w in state.warnings[-5:]:
            parts.append(f"⚠ {w}")
        body = "\n".join(parts) if parts else "—"
        return Panel(Text(body), title="Errors & warnings", border_style="yellow")

    async def action_record(self) -> None:
        st = self.store.get_state()
        title = f"Meeting {datetime.now().isoformat(timespec='seconds')}"
        await self.store.dispatch_with_effects(
            act.RecordingStartRequested(
                title=title,
                audio_source=st.audio_source,
                at=utc_now(),
            )
        )

    async def action_stop(self) -> None:
        await self.store.dispatch_with_effects(act.RecordingStopRequested(at=utc_now()))

    async def action_export_md(self) -> None:
        tabs = self.query_one(TabbedContent)
        if tabs.active == "tab-meetings":
            browser = self.query_one("#meeting-browser", MeetingBrowser)
            sid = browser.selected_session_id
            if sid is None:
                self.notify("Select a meeting in the Meetings tab to export.", severity="warning")
                return
            await self.store.dispatch_with_effects(
                act.ExportMarkdownRequested(at=utc_now(), session_id=sid)
            )
            return
        await self.store.dispatch_with_effects(act.ExportMarkdownRequested(at=utc_now()))

    async def action_summarize(self) -> None:
        tabs = self.query_one(TabbedContent)
        if tabs.active == "tab-meetings":
            browser = self.query_one("#meeting-browser", MeetingBrowser)
            sid = browser.selected_session_id
            if sid is None:
                self.notify(
                    "Select a meeting in the Meetings tab to summarize.", severity="warning"
                )
                return
            await self.store.dispatch_with_effects(
                act.SummarizeSessionRequested(at=utc_now(), session_id=sid)
            )
            return
        await self.store.dispatch_with_effects(act.SummarizeSessionRequested(at=utc_now()))

    def action_settings(self) -> None:
        self.store.dispatch(act.SettingsScreenOpened(at=utc_now()))
        self.push_screen(SettingsScreen())

    def action_sessions(self) -> None:
        self.store.dispatch(act.SessionsScreenOpened(at=utc_now()))
        self.push_screen(SessionsScreen())

    def action_ack_errors(self) -> None:
        st = self.store.get_state()
        for e in select_unacknowledged_errors(st):
            self.store.dispatch(act.ErrorAcknowledged(error_id=e.id, at=utc_now()))

    async def action_quit(self) -> None:
        await self.store.dispatch_with_effects(act.RecordingStopRequested(at=utc_now()))
        self.exit()


def _configure_logging_from_settings(settings: Settings) -> None:
    log_path = settings.resolved_log_file() if settings.log_enable_file else None
    configure_logging(
        settings.log_level,
        log_file=log_path,
        log_file_max_bytes=settings.log_file_max_bytes,
        log_file_backup_count=settings.log_file_backup_count,
    )


def run_tui_attached(
    *,
    container: Container,
    settings: Settings,
    configure_log: bool = True,
) -> None:
    """Run the Textual UI using an existing container (caller owns lifecycle)."""
    if configure_log:
        _configure_logging_from_settings(settings)
    store = Store()
    controller = TuiController(store=store, container=container, settings=settings)
    store.register_effects(controller.handle)
    TranscriberApp(store=store, container=container).run()


def run_tui() -> None:
    """Standalone entry: build container, run UI, then close."""
    settings = load_settings()
    _configure_logging_from_settings(settings)
    try:
        container = build_container(settings)
    except ProviderSelectionError as e:
        raise SystemExit(str(e)) from e

    try:
        run_tui_attached(container=container, settings=settings, configure_log=False)
    finally:
        container.close()
