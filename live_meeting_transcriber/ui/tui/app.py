from __future__ import annotations

import asyncio
import contextlib
import functools
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from uuid import UUID

from rich.console import Group
from rich.panel import Panel
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.content import Content
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import (
    Button,
    DataTable,
    DirectoryTree,
    Footer,
    Header,
    Input,
    RichLog,
    Select,
    Static,
    TabbedContent,
    TabPane,
    TextArea,
)

from live_meeting_transcriber.application.cleanup_service import purge_session_artifacts
from live_meeting_transcriber.application.container import (
    Container,
    ProviderSelectionError,
    build_container,
)
from live_meeting_transcriber.config.settings import (
    Settings,
    load_settings,
    save_settings,
)
from live_meeting_transcriber.observability.logging import configure_logging
from live_meeting_transcriber.ui.effects.controller import TuiController
from live_meeting_transcriber.ui.state import actions as act
from live_meeting_transcriber.ui.state.model import AppState, RecordingStatus, TranscriptLineState
from live_meeting_transcriber.ui.state.selectors import (
    build_live_status_lines,
    select_display_speaker,
    select_errors_compact_summary,
    select_header_title,
    select_is_recording,
    select_transcript_timestamp,
    select_unacknowledged_errors,
)
from live_meeting_transcriber.ui.state.store import Store
from live_meeting_transcriber.ui.tui.empty_states import (
    LIVE_EMPTY_HINT,
    SESSIONS_EMPTY_HINT,
    audio_prerequisite_warnings,
)
from live_meeting_transcriber.ui.tui.meeting_browser import (
    ConfirmDeleteMeetingModal,
    ConfirmOverwriteExportModal,
    MeetingBrowser,
    SummaryContextModal,
)
from live_meeting_transcriber.ui.tui.people_suggesters import (
    CommaSeparatedPeopleSuggester,
    PeoplePrefixSuggester,
)
from live_meeting_transcriber.ui.tui.settings_edit import (
    PATH_SETTING_SPECS,
    PathKind,
    apply_path_edits,
    current_path,
    validate_path_selection,
)
from live_meeting_transcriber.ui.tui.settings_view import build_settings_sections
from live_meeting_transcriber.ui.tui.slide_preview_helpers import (
    ensure_textual_image_protocol_probe,
)
from live_meeting_transcriber.ui.tui.tab_complete_input import TabCompletableInput
from live_meeting_transcriber.utils.time import format_clock, format_local_datetime, utc_now


class SettingsScreen(ModalScreen[None]):
    """Read-only settings overview (values come from store only)."""

    BINDINGS = [
        Binding("e", "edit", "Edit paths", show=True),
        Binding("escape", "close", "Close", show=True),
    ]

    def compose(self) -> ComposeResult:
        app = self.app
        assert isinstance(app, TranscriberApp)
        state = app.store.get_state()
        blocks: list[str] = []
        for title, lines in build_settings_sections(state):
            body = "\n".join(f"  {line}" for line in lines)
            blocks.append(f"[bold]{title}[/]\n{body}")
        yield Vertical(
            Static("Settings (read-only)", classes="settings-title"),
            Static("\n\n".join(blocks), id="settings-body"),
            Static("e: edit folders/files   esc: close", classes="hint"),
            classes="settings-dialog",
        )

    def action_edit(self) -> None:
        self.app.push_screen(EditSettingsScreen())

    def action_close(self) -> None:
        app = self.app
        assert isinstance(app, TranscriberApp)
        app.store.dispatch(act.SettingsScreenClosed(at=utc_now()))
        self.dismiss()


class PathPickerScreen(ModalScreen[Path | None]):
    """Folder/file picker for a path-typed setting (U21).

    Browsing the :class:`DirectoryTree` fills the path input; ``Select`` validates the
    choice (must exist and match ``kind``) and dismisses with the resolved absolute path.
    ``Cancel``/escape dismiss with ``None``.
    """

    BINDINGS = [
        Binding("ctrl+s", "select", "Select", show=True, priority=True),
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    def __init__(self, *, kind: PathKind, start: Path | None, title: str) -> None:
        super().__init__()
        self._kind: PathKind = kind
        self._title = title
        self._root = self._pick_root(start)
        self._start = start

    @staticmethod
    def _pick_root(start: Path | None) -> Path:
        base = start if start is not None else Path.home()
        # For a file, browse its containing folder; fall back to home if it is gone.
        candidate = base if base.is_dir() else base.parent
        return candidate if candidate.is_dir() else Path.home()

    def compose(self) -> ComposeResult:
        what = "folder" if self._kind == "dir" else "file"
        yield Vertical(
            Static(self._title, classes="settings-title"),
            Static(f"Pick a {what}. Enter path or browse below.", classes="hint"),
            Input(value=str(self._start) if self._start else "", id="picker-path"),
            DirectoryTree(str(self._root), id="picker-tree"),
            Horizontal(
                Button("Select", id="picker-select", variant="primary"),
                Button("Cancel", id="picker-cancel"),
                classes="settings-actions",
            ),
            Static("ctrl+s: select   esc: cancel", classes="hint"),
            classes="settings-dialog",
        )

    def on_directory_tree_directory_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        self.query_one("#picker-path", Input).value = str(event.path)

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        self.query_one("#picker-path", Input).value = str(event.path)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "picker-select":
            await self.action_select()
        elif event.button.id == "picker-cancel":
            self.action_cancel()

    async def action_select(self) -> None:
        raw = self.query_one("#picker-path", Input).value.strip()
        if not raw:
            self.app.notify("Enter or pick a path first.", severity="warning")
            return
        chosen = Path(raw).expanduser().resolve()
        error = validate_path_selection(chosen, self._kind)
        if error is not None:
            self.app.notify(error, severity="error")
            return
        self.dismiss(chosen)

    def action_cancel(self) -> None:
        self.dismiss(None)


class EditSettingsScreen(ModalScreen[None]):
    """Edit path-typed settings through a picker and save to the YAML store (U21).

    Loads the currently resolved settings, lets the operator Browse/Clear each path field,
    and on Save writes the full settings set to ``config.yaml`` via :func:`save_settings`.
    Path changes take effect on restart (the running session keeps its loaded config).
    """

    BINDINGS = [
        Binding("ctrl+s", "save", "Save", show=True, priority=True),
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._settings = load_settings()
        self._pending: dict[str, Path | None] = {}

    @staticmethod
    def _display(value: Path | None) -> str:
        return str(value) if value is not None else "(not set)"

    def compose(self) -> ComposeResult:
        rows: list[Widget] = [
            Static("Edit folders & files", classes="settings-title"),
            Static("Changes are saved to config.yaml and apply after restart.", classes="hint"),
        ]
        for spec in PATH_SETTING_SPECS:
            value = current_path(self._settings, spec.field)
            rows.append(Static(f"[bold]{spec.label}[/] — {spec.help}"))
            rows.append(Static(self._display(value), id=f"val-{spec.field}"))
            rows.append(
                Horizontal(
                    Button("Browse…", id=f"browse-{spec.field}"),
                    Button("Clear", id=f"clear-{spec.field}"),
                    classes="settings-actions",
                )
            )
        rows.append(
            Horizontal(
                Button("Save", id="settings-save", variant="primary"),
                Button("Cancel", id="settings-cancel"),
                classes="settings-actions",
            )
        )
        rows.append(Static("ctrl+s: save   esc: cancel", classes="hint"))
        yield Vertical(*rows, classes="settings-dialog settings-edit")

    def set_pending(self, field: str, value: Path | None) -> None:
        """Record a pending edit and refresh the row's displayed value."""
        self._pending[field] = value
        with contextlib.suppress(NoMatches):
            self.query_one(f"#val-{field}", Static).update(self._display(value))

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid == "settings-save":
            await self.action_save()
        elif bid == "settings-cancel":
            self.action_cancel()
        elif bid.startswith("browse-"):
            self._open_picker(bid.removeprefix("browse-"))
        elif bid.startswith("clear-"):
            self.set_pending(bid.removeprefix("clear-"), None)

    def _open_picker(self, field: str) -> None:
        spec = next(s for s in PATH_SETTING_SPECS if s.field == field)
        pending = self._pending.get(field, current_path(self._settings, field))

        def _apply(result: Path | None) -> None:
            if result is not None:
                self.set_pending(field, result)

        self.app.push_screen(
            PathPickerScreen(kind=spec.kind, start=pending, title=spec.label),
            callback=_apply,
        )

    async def action_save(self) -> None:
        edited = apply_path_edits(self._settings, self._pending)
        try:
            path = save_settings(edited)
        except OSError as e:
            self.app.notify(f"Could not save settings: {e}", severity="error")
            return
        self.app.notify(f"Saved to {path}. Restart to apply.", severity="information")
        self.dismiss()

    def action_cancel(self) -> None:
        self.dismiss()


class AudioSourcesScreen(ModalScreen[None]):
    """Pick the monitor/system source and microphone from available devices.

    The choice is persisted (device_prefs.json) and applied on the next recording.
    """

    BINDINGS = [
        Binding("ctrl+s", "save", "Save", show=True, priority=True),
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    _MIC_NONE = "\x00none"  # sentinel option value for "monitor only / no microphone"

    def compose(self) -> ComposeResult:
        app = self.app
        assert isinstance(app, TranscriberApp)
        state = app.store.get_state()
        try:
            sources = app.container.devices.list_sources()
        except Exception as e:  # device probing can fail (e.g. ffmpeg missing)
            yield Vertical(
                Static("Audio sources", classes="settings-title"),
                Static(f"Could not list audio devices: {e}"),
                Static("esc: close", classes="hint"),
                classes="settings-dialog",
            )
            return

        device_opts = [(f"{s.description}  [{s.name}]", s.name) for s in sources]

        def _value_for(current: str | None) -> object:
            names = [name for _label, name in device_opts]
            return current if current in names else Select.BLANK

        mic_current = state.configured_microphone_source or state.microphone_source
        mic_opts = [("(monitor only — no microphone)", self._MIC_NONE), *device_opts]
        mic_value: object = self._MIC_NONE if mic_current is None else _value_for(mic_current)

        yield Vertical(
            Static("Audio sources", classes="settings-title"),
            Static("Applied on the next recording. ctrl+s: save   esc: cancel", classes="hint"),
            Static("Monitor / system source (meeting audio):"),
            Select(device_opts, value=_value_for(state.audio_source), id="monitor-select"),
            Static("Microphone source (you):"),
            Select(mic_opts, value=mic_value, allow_blank=True, id="mic-select"),
            classes="settings-dialog",
        )

    async def action_save(self) -> None:
        app = self.app
        assert isinstance(app, TranscriberApp)
        try:
            monitor = self.query_one("#monitor-select", Select)
            mic = self.query_one("#mic-select", Select)
        except NoMatches:
            self.dismiss()
            return

        mon_val = monitor.value
        monitor_source = None if mon_val is Select.BLANK else str(mon_val)

        mic_val = mic.value
        if mic_val is Select.BLANK or mic_val == self._MIC_NONE:
            microphone_source: str | None = None
        else:
            microphone_source = str(mic_val)

        await app.store.dispatch_with_effects(
            act.AudioSourcesSelected(
                monitor_source=monitor_source,
                microphone_source=microphone_source,
                at=utc_now(),
            )
        )
        app.notify("Audio sources saved (applies next recording).", severity="information")
        self.dismiss()

    def action_cancel(self) -> None:
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


class EditMeetingDetailsScreen(ModalScreen[None]):
    """Edit the current live meeting's title, context/notes, attendees, and speaker names.

    Title/notes/attendees are persisted via SessionDetailsCommitRequested; the notes carry
    into the summary-context prompt at summarize-time. Any speaker keys already detected in
    the live session can be named here — the alias applies immediately (transcript relabels)
    and persists, without waiting for post-stop cleanup.
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True, priority=True),
        Binding("ctrl+enter,ctrl+return", "save", "Save", show=True, priority=True),
    ]

    def __init__(
        self,
        session_id: str,
        *,
        title: str,
        notes: str,
        attendees: list[str],
        detected_speakers: list[str],
        speaker_aliases: dict[str, str],
    ) -> None:
        super().__init__()
        self.session_id = session_id
        self._title = title
        self._notes = notes
        self._attendees = attendees
        self._detected_speakers = detected_speakers
        self._speaker_aliases = speaker_aliases

    def compose(self) -> ComposeResult:
        children: list[Static | TabCompletableInput | TextArea | Horizontal] = [
            Static("Meeting details", classes="settings-title"),
            Static("Ctrl+Enter: save   Esc: cancel", classes="dim"),
            Static("Title"),
            TabCompletableInput(value=self._title, placeholder="Title", id="details-title"),
            Static("Context / notes (used to guide the summary)"),
            TextArea(id="details-notes", language=None),
            Static("Attendees (comma-separated)"),
            TabCompletableInput(
                value=", ".join(self._attendees),
                placeholder="Alice, Bob, …",
                id="details-attendees",
            ),
            Static("Speaker names"),
        ]
        if self._detected_speakers:
            for key in self._detected_speakers:
                children.append(
                    Horizontal(
                        Static(f"{key} →", classes="spk-label"),
                        TabCompletableInput(
                            value=self._speaker_aliases.get(key, ""),
                            placeholder="Display name",
                            id=f"details-spk-{key}",
                        ),
                        classes="spk-row",
                    )
                )
        else:
            children.append(
                Static(
                    "No speakers detected yet — names appear once the meeting has audio.",
                    classes="dim",
                )
            )
        children.append(
            Horizontal(
                Button("Save", id="details-save", variant="primary"),
                Button("Cancel", id="details-cancel"),
            )
        )
        yield Vertical(*children, classes="settings-dialog")

    def on_mount(self) -> None:
        app = self.app
        assert isinstance(app, TranscriberApp)
        notes = self.query_one("#details-notes", TextArea)
        notes.text = self._notes
        self.query_one(
            "#details-attendees", TabCompletableInput
        ).suggester = CommaSeparatedPeopleSuggester(app.container.people)
        for key in self._detected_speakers:
            self.query_one(
                f"#details-spk-{key}", TabCompletableInput
            ).suggester = PeoplePrefixSuggester(app.container.people)
        self.query_one("#details-title", TabCompletableInput).focus()

    async def action_save(self) -> None:
        app = self.app
        assert isinstance(app, TranscriberApp)
        title = self.query_one("#details-title", TabCompletableInput).value.strip()
        if not title:
            app.notify("Title required.", severity="error")
            return
        notes = self.query_one("#details-notes", TextArea).text
        raw_att = self.query_one("#details-attendees", TabCompletableInput).value
        parts = [p.strip() for p in raw_att.replace("\n", ",").split(",")]
        attendees = [p for p in parts if p]
        await app.store.dispatch_with_effects(
            act.SessionDetailsCommitRequested(
                session_id=UUID(self.session_id),
                title=title,
                notes=notes,
                attendees=attendees,
                at=utc_now(),
            )
        )
        for name in attendees:
            app.container.people.touch(name)
        self._save_speaker_aliases(app)
        self.dismiss()

    def _save_speaker_aliases(self, app: TranscriberApp) -> None:
        """Persist detected-speaker display names and refresh live state so labels update."""
        if not self._detected_speakers:
            return
        mapping = {
            key: self.query_one(f"#details-spk-{key}", TabCompletableInput).value.strip()
            for key in self._detected_speakers
        }
        app.container.session_speakers.replace_map(UUID(self.session_id), mapping)
        for key, name in mapping.items():
            if name:
                app.store.dispatch(
                    act.SpeakerAliasUpdated(speaker_key=key, alias=name, at=utc_now())
                )
                app.container.people.touch(name)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid == "details-save":
            await self.action_save()
        elif bid == "details-cancel":
            self.action_cancel()

    def action_cancel(self) -> None:
        self.dismiss()


class SessionsScreen(ModalScreen[None]):
    """Browse and rename sessions from the local database."""

    BINDINGS = [
        Binding("escape", "close", "Close", show=True),
        Binding("r", "refresh", "Refresh", show=True),
        Binding("e", "edit_title", "Edit title", show=True),
        Binding("c", "copy_id", "Copy ID", show=True),
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
            Static("", id="sessions-empty", classes="dim"),
            Static(
                "r: refresh   e: rename   c: copy id   d: delete selected   esc: close",
                classes="hint",
            ),
            classes="settings-dialog",
        )

    def on_mount(self) -> None:
        app = self.app
        assert isinstance(app, TranscriberApp)
        table = self.query_one("#sessions-table", DataTable)
        table.add_columns("Title", "Started", "Ended")
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
            ended = format_local_datetime(row.ended_at) if row.ended_at else "—"
            table.add_row(
                row.title[:56] + ("…" if len(row.title) > 56 else ""),
                format_local_datetime(row.started_at),
                ended,
                key=row.id,
            )
        # First-run/empty state: guide the user instead of showing an empty grid (U10).
        empty = self.query_one("#sessions-empty", Static)
        empty.update(SESSIONS_EMPTY_HINT if not state.sessions_catalog else "")

    def _selected_row_id(self) -> str | None:
        table = self.query_one("#sessions-table", DataTable)
        coord = table.cursor_coordinate
        if coord is None or coord.row < 0 or coord.row >= len(self._row_ids):
            return None
        return self._row_ids[coord.row]

    async def action_copy_id(self) -> None:
        sid = self._selected_row_id()
        if sid is None:
            self.app.notify("Select a session row first.", severity="warning")
            return
        self.app.copy_to_clipboard(sid)
        self.app.notify(f"Copied session ID: {sid}")

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
            purge_session_artifacts(
                app.container.settings.ensure_data_dir(),
                sid,
                dry_run=False,
            )
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
        Binding("t", "meeting_details", "Meeting details", show=True),
        Binding("w", "export_md", "Export", show=True, priority=True),
        Binding("k", "summarize", "Summarize", show=True, priority=True),
        Binding("s", "settings", "Settings", show=True),
        Binding("a", "audio_sources", "Audio sources", show=True),
        Binding("m", "sessions", "Sessions", show=True),
        Binding("c", "ack_errors", "Ack errors", show=True),
        Binding("ctrl+1", "focus_live_tab", "Live tab", show=True),
        Binding("ctrl+2", "focus_meetings_tab", "Meetings tab", show=True),
        Binding("ctrl+3", "focus_logs_tab", "Logs tab", show=True),
        Binding("ctrl+i", "finalize_speakers", "Speaker ID", show=True, priority=True),
    ]

    CSS = """
    TabbedContent { height: 1fr; }
    TabPane { height: 1fr; }
    #tab-live #main-row { height: 1fr; }
    #sidebar { width: 32; min-width: 32; border: solid $primary; }
    #transcript { border: solid $accent; min-width: 40; }
    #status { height: auto; padding: 0 1; }
    #notices { height: auto; padding: 0 1; border-top: solid $boost; text-style: italic; color: $success; }
    #errors { height: auto; max-height: 20; overflow-y: auto; padding: 0 1; border-top: solid $boost; }
    #meeting-browser { height: 1fr; }
    #meeting-browser-split { height: 1fr; min-height: 8; }
    #meeting-sessions-table { width: 38; min-width: 28; }
    #meeting-browser-detail { height: 1fr; min-height: 8; }
    #meeting-notes { height: 7; min-height: 4; max-height: 12; }
    #meeting-summary { height: 10; min-height: 5; max-height: 18; }
    #meeting-transcript { height: 1fr; min-height: 8; }
    .spk-row { height: auto; margin-bottom: 1; }
    .spk-label { width: 14; }
    .dim { text-style: dim; }
    .settings-dialog { padding: 1 2; width: 90; height: auto; max-height: 90%; background: $surface; border: thick $accent; }
    .settings-title { text-style: bold; }
    .hint { padding-top: 1; text-style: dim; }
    #slide-preview-dialog { width: 95%; height: 90%; min-height: 28; max-width: 120; padding: 1 2; background: $surface; border: thick $accent; layout: vertical; overflow: hidden; }
    #slide-preview-params { height: auto; max-height: 7; margin-bottom: 1; }
    #slide-preview-status { height: auto; max-height: 4; margin-bottom: 1; overflow-y: auto; }
    #slide-preview-split { height: 1fr; min-height: 12; }
    #slide-candidates-table { width: 1fr; min-width: 28; height: 1fr; min-height: 8; }
    #slide-image-pane { width: 1fr; min-width: 24; height: 1fr; min-height: 8; border: solid $boost; padding: 0 1; }
    #slide-preview-actions { dock: bottom; width: 100%; height: auto; padding-top: 1; background: $surface; }
    #slide-preview-actions Button { margin-right: 1; }
    #slide-preview-hint { dock: bottom; width: 100%; height: auto; padding-top: 1; background: $surface; }
    #sessions-table { height: 20; min-height: 8; }
    #tab-logs { height: 1fr; }
    #ui-activity-log { height: 1fr; min-height: 10; border: solid $boost; }
    """

    def __init__(self, *, store: Store, container: Container, controller: TuiController) -> None:
        super().__init__()
        self.store = store
        self.container = container
        self._controller = controller
        self._last_segment_keys: tuple[tuple[str, str, str], ...] | None = None
        self._last_ui_log_len: int = 0

    def format_title(self, title: str, sub_title: str) -> Content:
        """Header shows meeting context only — the app name (``title``) is not repeated
        inside the app (U19). ``self.title`` stays set so app identity remains available
        for the command palette and terminal title. Falls back to the app name only when
        there is no context to show.
        """
        return Content(sub_title or title)

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
            with TabPane("Logs", id="tab-logs"), Vertical(id="logs-pane"):
                yield Static(
                    "[bold]Activity log[/] — errors/warnings from the Live tab, WhisperX finalize "
                    "progress, and other messages. Also written to the log file when file logging is on. "
                    "[dim]ctrl+3[/]",
                    id="logs-header",
                )
                yield RichLog(id="ui-activity-log", highlight=True, markup=True, auto_scroll=True)
        yield Footer()

    def action_focus_live_tab(self) -> None:
        self.query_one(TabbedContent).active = "tab-live"

    def action_focus_meetings_tab(self) -> None:
        self.query_one(TabbedContent).active = "tab-meetings"

    def action_focus_logs_tab(self) -> None:
        self.query_one(TabbedContent).active = "tab-logs"

    async def on_mount(self) -> None:
        self.store.subscribe(self._on_state)
        self._controller.confirm_export_overwrite = self._confirm_export_overwrite
        # Tick the live elapsed-time display once a second while recording. The reducer owns
        # recording_started_at; this only re-renders the status block against the wall clock.
        self.set_interval(1.0, self._tick_elapsed)
        await self.store.dispatch_with_effects(act.AppStarted(at=utc_now()))
        self._run_startup_checks()

    def _run_startup_checks(self) -> None:
        """Non-blocking first-run prerequisite checks (U10).

        Surfaces missing audio prerequisites as warnings in the errors/warnings
        panel with remediation text. Never blocks launch — a failing probe is
        reported, not raised.
        """
        for message in audio_prerequisite_warnings(self.container.devices.list_sources):
            self.store.dispatch(act.WarningRaised(message=message, at=utc_now()))

    def _tick_elapsed(self) -> None:
        state = self.store.get_state()
        if not select_is_recording(state):
            return
        try:
            status = self.query_one("#status", Static)
        except NoMatches:
            # Main screen not mounted (a modal is up or teardown) — skip; re-renders next tick.
            return
        status.update(self._render_status(state))

    def _on_state(self, state: AppState) -> None:
        self.sub_title = select_header_title(state)
        try:
            status = self.query_one("#status", Static)
            notices = self.query_one("#notices", Static)
            err_panel = self.query_one("#errors", Static)
            log = self.query_one("#transcript", RichLog)
        except NoMatches:
            # Main screen isn't mounted (app shutting down, or a modal screen is active).
            # State updates dispatched during teardown — e.g. background finalize progress —
            # can arrive after the widgets are gone; skip rendering (a live app re-renders
            # on the next dispatch).
            return

        status.update(self._render_status(state))
        if state.notices:
            notices.update(
                Text.from_markup(
                    "[bold]Last actions[/]\n" + "\n".join(f"• {n}" for n in state.notices[-4:])
                )
            )
        else:
            notices.update(
                Text.from_markup(
                    "[dim]w: export · k: summarize · ctrl+i: speaker ID · ctrl+3: logs[/]"
                )
            )
        err_panel.update(self._render_errors(state))

        ui_log = self.query_one("#ui-activity-log", RichLog)
        log_lines = state.ui_log_lines
        if len(log_lines) < self._last_ui_log_len:
            ui_log.clear()
            self._last_ui_log_len = 0
        if len(log_lines) > self._last_ui_log_len:
            for log_line in log_lines[self._last_ui_log_len :]:
                ui_log.write(Text.from_markup(log_line))
            self._last_ui_log_len = len(log_lines)

        def _seg_key(seg: TranscriptLineState) -> tuple[str, str, str]:
            return (seg.id, seg.speaker, seg.text)

        new_keys = tuple(_seg_key(s) for s in state.recent_transcript_segments)
        old_keys = self._last_segment_keys

        if (
            # Truthy (not None *and* non-empty): an empty prior transcript must fall
            # through to the clearing branch below so the first-run hint is wiped
            # before the first segment is written, not left pinned above it (U10).
            old_keys and len(new_keys) > len(old_keys) and new_keys[: len(old_keys)] == old_keys
        ):
            for line in state.recent_transcript_segments[len(old_keys) :]:
                sp = select_display_speaker(state, line.speaker)
                ts = select_transcript_timestamp(line)
                log.write(Text.from_markup(f"[dim]{ts}[/] [bold]{sp}[/]\n{line.text}"))
        elif old_keys != new_keys:
            log.clear()
            if not state.recent_transcript_segments:
                # First-run / emptied transcript: show a guidance line instead of a
                # blank pane (U10). Replaced as soon as real segments arrive.
                log.write(Text.from_markup(LIVE_EMPTY_HINT))
            for line in state.recent_transcript_segments:
                sp = select_display_speaker(state, line.speaker)
                ts = select_transcript_timestamp(line)
                log.write(Text.from_markup(f"[dim]{ts}[/] [bold]{sp}[/]\n{line.text}"))
        self._last_segment_keys = new_keys

    def _render_status(self, state: AppState) -> Group:
        lines = build_live_status_lines(state, utc_now())
        return Group(*[Text.from_markup(x) for x in lines])

    def _render_errors(self, state: AppState) -> Panel | Text:
        # When there is nothing to report, collapse the bordered panel into a
        # single dim line so the sidebar reclaims the rows (U8). The panel only
        # reappears once there is an actual error or warning to show.
        compact = select_errors_compact_summary(state)
        if compact is not None:
            return Text.from_markup(f"[dim]{compact}[/]")
        unacked = select_unacknowledged_errors(state)
        parts: list[str] = []
        for e in unacked[-8:]:
            parts.append(f"• [{format_clock(e.at)}] {e.message}")
        for w in state.warnings[-5:]:
            parts.append(f"⚠ {w}")
        body = "\n".join(parts) if parts else "—"
        return Panel(Text(body), title="Errors & warnings", border_style="yellow")

    async def action_record(self) -> None:
        st = self.store.get_state()
        if st.recording_status in (
            RecordingStatus.starting,
            RecordingStatus.recording,
            RecordingStatus.stopping,
        ):
            self.notify("Recording already in progress.", severity="warning")
            return

        resume_session_id: UUID | None = None
        title = f"Meeting {datetime.now().isoformat(timespec='seconds')}"
        if st.recording_status == RecordingStatus.failed and st.current_session_id is not None:
            resume_session_id = st.current_session_id
            title = st.session_title or title
            self.notify(f"Resuming meeting: {title}", severity="information")

        await self.store.dispatch_with_effects(
            act.RecordingStartRequested(
                title=title,
                audio_source=st.audio_source,
                at=utc_now(),
                resume_session_id=resume_session_id,
                microphone_source=st.configured_microphone_source,
            )
        )

    async def action_stop(self) -> None:
        await self.store.dispatch_with_effects(act.RecordingStopRequested(at=utc_now()))

    def action_meeting_details(self) -> None:
        """Edit the current live meeting's title/context/attendees/speakers (Live tab)."""
        state = self.store.get_state()
        sid = state.current_session_id
        if sid is None:
            self.notify("Start (or resume) a meeting on the Live tab first.", severity="warning")
            return
        session = self.container.sessions.get(sid)
        if session is None:
            self.notify("Session not found.", severity="warning")
            return
        self.push_screen(
            EditMeetingDetailsScreen(
                str(sid),
                title=session.title,
                notes=session.notes,
                attendees=list(session.attendees),
                detected_speakers=sorted(state.diarization_detected_speakers),
                speaker_aliases=dict(state.speaker_aliases),
            )
        )

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
        sid: UUID | None = None
        if tabs.active == "tab-meetings":
            browser = self.query_one("#meeting-browser", MeetingBrowser)
            sid = browser.selected_session_id
            if sid is None:
                self.notify(
                    "Select a meeting in the Meetings tab to summarize.", severity="warning"
                )
                return
        else:
            sid = self.store.get_state().current_session_id
        # Pre-fill the context box with any notes the operator set during the live meeting
        # (U20) so they don't have to re-enter them at summarize-time.
        initial = ""
        if sid is not None:
            session = self.container.sessions.get(sid)
            if session is not None:
                initial = session.notes
        await self.push_screen(
            SummaryContextModal(initial=initial),
            callback=functools.partial(self._after_global_summary_context, sid),
        )

    def _after_global_summary_context(self, sid: UUID | None, context: str | None) -> None:
        if context is None:
            return
        user_ctx = context or None

        async def _dispatch() -> None:
            await self.store.dispatch_with_effects(
                act.SummarizeSessionRequested(
                    at=utc_now(),
                    session_id=sid,
                    user_context=user_ctx,
                )
            )

        self.run_worker(_dispatch(), exclusive=True)

    async def action_finalize_speakers(self) -> None:
        tabs = self.query_one(TabbedContent)
        sid: UUID | None = None
        if tabs.active == "tab-meetings":
            browser = self.query_one("#meeting-browser", MeetingBrowser)
            sid = browser.selected_session_id
        if sid is None:
            sid = self.store.get_state().current_session_id
        if sid is None:
            self.notify(
                "Select a meeting on the Meetings tab, or start recording on Live.",
                severity="warning",
            )
            return
        self.notify(
            "Running speaker ID (WhisperX) — this may take a while…",
            severity="information",
        )
        await self.store.dispatch_with_effects(
            act.FinalizeSessionRequested(session_id=sid, at=utc_now())
        )

    def action_settings(self) -> None:
        self.store.dispatch(act.SettingsScreenOpened(at=utc_now()))
        self.push_screen(SettingsScreen())

    def action_audio_sources(self) -> None:
        self.push_screen(AudioSourcesScreen())

    def action_sessions(self) -> None:
        self.store.dispatch(act.SessionsScreenOpened(at=utc_now()))
        self.push_screen(SessionsScreen())

    def action_ack_errors(self) -> None:
        st = self.store.get_state()
        for e in select_unacknowledged_errors(st):
            self.store.dispatch(act.ErrorAcknowledged(error_id=e.id, at=utc_now()))

    async def _confirm_export_overwrite(self, path: Path) -> bool:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[bool] = loop.create_future()

        def _done(confirmed: bool | None) -> None:
            if not future.done():
                future.set_result(bool(confirmed))

        await self.push_screen(
            ConfirmOverwriteExportModal(path=path),
            callback=_done,
        )
        return await future

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
    ensure_textual_image_protocol_probe()
    store = Store()
    controller = TuiController(store=store, container=container, settings=settings)
    store.register_effects(controller.handle)
    TranscriberApp(store=store, container=container, controller=controller).run()


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
