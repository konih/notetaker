from __future__ import annotations

import asyncio
import contextlib
import functools
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from rich.console import Group
from rich.panel import Panel
from rich.text import Text
from textual import events
from textual.app import App, ComposeResult, SystemCommand
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import ModalScreen, Screen
from textual.widget import Widget
from textual.widgets import (
    Button,
    DataTable,
    DirectoryTree,
    Footer,
    Input,
    RichLog,
    Select,
    Static,
    Switch,
    TabbedContent,
    TabPane,
    TextArea,
)

from live_meeting_transcriber.application.container import (
    Container,
    ProviderSelectionError,
    build_container,
)
from live_meeting_transcriber.application.dual_path import dual_path_downgrade_reason
from live_meeting_transcriber.application.session_search import fuzzy_match
from live_meeting_transcriber.config.settings import (
    Settings,
    load_settings,
    save_settings,
)
from live_meeting_transcriber.observability.logging import configure_logging
from live_meeting_transcriber.ui.effects.controller import (
    TuiController,
    settings_loaded_action,
)
from live_meeting_transcriber.ui.state import actions as act
from live_meeting_transcriber.ui.state.model import (
    AppState,
    RecordingStatus,
    SessionRowState,
    TranscriptLineState,
)
from live_meeting_transcriber.ui.state.selectors import (
    build_audio_card_lines,
    build_pipeline_card_lines,
    build_session_card_lines,
    select_display_speaker,
    select_errors_compact_summary,
    select_is_recording,
    select_transcript_timestamp,
    select_unacknowledged_errors,
)
from live_meeting_transcriber.ui.state.store import Store
from live_meeting_transcriber.ui.tui import meeting_actions
from live_meeting_transcriber.ui.tui.empty_states import (
    LIVE_EMPTY_HINT,
    SESSIONS_EMPTY_HINT,
    audio_prerequisite_warnings,
)
from live_meeting_transcriber.ui.tui.footer_bindings import (
    FOOTER_ACTIONS,
    overflow_footer_actions,
)
from live_meeting_transcriber.ui.tui.meeting_browser import MeetingBrowser
from live_meeting_transcriber.ui.tui.meeting_modals import (
    ConfirmOverwriteExportModal,
    SummaryContextModal,
)
from live_meeting_transcriber.ui.tui.people_suggesters import (
    CommaSeparatedPeopleSuggester,
    PeoplePrefixSuggester,
)
from live_meeting_transcriber.ui.tui.rendering import transcript_segment_text
from live_meeting_transcriber.ui.tui.settings_edit import (
    PATH_SETTING_SPECS,
    SCALAR_SETTING_SPECS,
    PathKind,
    ScalarValue,
    apply_path_edits,
    apply_scalar_edits,
    current_path,
    current_scalar,
    parse_scalar_text,
    validate_path_selection,
    validate_scalar_edits,
)
from live_meeting_transcriber.ui.tui.settings_view import build_settings_sections
from live_meeting_transcriber.ui.tui.slide_preview_helpers import (
    ensure_textual_image_protocol_probe,
)
from live_meeting_transcriber.ui.tui.status_deck import StatusDeck
from live_meeting_transcriber.ui.tui.tab_complete_input import TabCompletableInput
from live_meeting_transcriber.ui.tui.theme import NOTETAKER_DARK
from live_meeting_transcriber.utils.time import format_clock, format_local_datetime, utc_now


class HelpScreen(ModalScreen[None]):
    """U16 — ``?`` overlay listing every keyboard shortcut (global + Meetings tab).

    Content is a pure projection of the live ``BINDINGS`` (see ``help_overlay``), so it
    stays in sync automatically and keeps the trimmed U4 footer's overflow shortcuts
    discoverable.
    """

    BINDINGS = [
        Binding("escape", "close", "Close", show=True),
        Binding("question_mark", "close", "Close", show=False),
        Binding("q", "close", "Close", show=False),
    ]

    def compose(self) -> ComposeResult:
        from live_meeting_transcriber.ui.tui.help_overlay import (
            build_help_sections,
            format_help_markup,
        )

        sections = build_help_sections(type(self.app).BINDINGS, MeetingBrowser.BINDINGS)
        yield Vertical(
            Static("Keyboard shortcuts", classes="settings-title"),
            VerticalScroll(Static(format_help_markup(sections)), classes="help-scroll"),
            Static("? or esc: close", classes="hint"),
            classes="help-dialog",
        )

    def action_close(self) -> None:
        self.dismiss()


class SettingsScreen(ModalScreen[None]):
    """Read-only settings overview (values come from store only)."""

    BINDINGS = [
        Binding("e", "edit", "Edit settings", show=True),
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
            Static("e: edit settings   esc: close", classes="hint"),
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
    """Edit safe runtime toggles and path-typed settings, saved to the YAML store (U21, U15).

    Loads the currently resolved settings, lets the operator flip the approved scalar
    toggles (switches for bools, validated inputs for numbers) and Browse/Clear each path
    field, and on Save writes the full settings set to ``config.yaml`` via
    :func:`save_settings`. Invalid numeric input is blocked with an inline error and
    nothing is written. All changes take effect on restart (the running session keeps its
    loaded config); the read-only Settings screen reflects the saved values immediately.
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
            Static("Edit settings", classes="settings-title"),
            Static("Changes are saved to config.yaml and apply after restart.", classes="hint"),
            Static("[bold]Runtime toggles[/]", classes="settings-section"),
        ]
        for scalar in SCALAR_SETTING_SPECS:
            scalar_value = current_scalar(self._settings, scalar.field)
            if scalar.kind == "bool":
                rows.append(
                    Horizontal(
                        Switch(value=bool(scalar_value), id=f"switch-{scalar.field}"),
                        Static(f"[bold]{scalar.label}[/] — {scalar.help}", classes="switch-label"),
                        classes="settings-switch-row",
                    )
                )
                continue
            rows.append(Static(f"[bold]{scalar.label}[/] — {scalar.help}"))
            rows.append(Input(value=str(scalar_value), id=f"input-{scalar.field}"))
            rows.append(Static("", id=f"err-{scalar.field}", classes="settings-error"))
        rows.append(Static("[bold]Folders & files[/]", classes="settings-section"))
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

    def _scalar_edits_from_widgets(self) -> tuple[dict[str, ScalarValue], dict[str, str]]:
        """Read every scalar widget; returns (edits, per-field parse errors)."""
        edits: dict[str, ScalarValue] = {}
        errors: dict[str, str] = {}
        for spec in SCALAR_SETTING_SPECS:
            if spec.kind == "bool":
                edits[spec.field] = self.query_one(f"#switch-{spec.field}", Switch).value
                continue
            raw = self.query_one(f"#input-{spec.field}", Input).value
            parsed = parse_scalar_text(spec.kind, raw)
            if parsed is None:
                errors[spec.field] = (
                    "Enter a whole number" if spec.kind == "int" else "Enter a number"
                )
                continue
            edits[spec.field] = parsed
        return edits, errors

    def _show_scalar_errors(self, errors: Mapping[str, str]) -> None:
        """Update every inline error line (clearing lines without an error)."""
        for spec in SCALAR_SETTING_SPECS:
            if spec.kind == "bool":
                continue
            with contextlib.suppress(NoMatches):
                self.query_one(f"#err-{spec.field}", Static).update(errors.get(spec.field, ""))

    async def action_save(self) -> None:
        scalar_edits, errors = self._scalar_edits_from_widgets()
        errors = {**validate_scalar_edits(self._settings, scalar_edits), **errors}
        self._show_scalar_errors(errors)
        if errors:
            self.app.notify("Fix the highlighted values — nothing was saved.", severity="error")
            return
        edited = apply_scalar_edits(apply_path_edits(self._settings, self._pending), scalar_edits)
        try:
            path = save_settings(edited)
        except OSError as e:
            self.app.notify(f"Could not save settings: {e}", severity="error")
            return
        app = self.app
        if isinstance(app, TranscriberApp):
            # Refresh the store so the read-only Settings screen shows the saved values;
            # the running recorder/controller keep their startup config until restart.
            app.store.dispatch(settings_loaded_action(edited, utc_now()))
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
            return current if current in names else Select.NULL

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
        monitor_source = None if mon_val is Select.NULL else str(mon_val)

        mic_val = mic.value
        if mic_val is Select.NULL or mic_val == self._MIC_NONE:
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


class NameSpeakersScreen(ModalScreen[None]):
    """Name detected speakers for the current live meeting.

    Title / context / attendees are edited inline on the Live tab (U23); this modal covers
    only speaker display names for keys already detected in the live session. Aliases apply
    immediately (transcript relabels) and persist via ``session_speakers.replace_map`` — a
    path distinct from session metadata, so there is no second editor of title/notes/attendees
    that could clobber the inline fields.
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True, priority=True),
        Binding("ctrl+s", "save", "Save", show=True, priority=True),
    ]

    def __init__(
        self,
        session_id: str,
        *,
        detected_speakers: list[str],
        speaker_aliases: dict[str, str],
    ) -> None:
        super().__init__()
        self.session_id = session_id
        self._detected_speakers = detected_speakers
        self._speaker_aliases = speaker_aliases

    def compose(self) -> ComposeResult:
        children: list[Static | TabCompletableInput | Horizontal] = [
            Static("Name speakers", classes="settings-title"),
            Static("Ctrl+S: save   Esc: cancel", classes="dim"),
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
                    "No speakers detected yet. Run Speaker ID on the finished meeting "
                    "(Meetings tab · Ctrl+D) to detect and name speakers.",
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
        for key in self._detected_speakers:
            self.query_one(
                f"#details-spk-{key}", TabCompletableInput
            ).suggester = PeoplePrefixSuggester(app.container.people)
        if self._detected_speakers:
            self.query_one(
                f"#details-spk-{self._detected_speakers[0]}", TabCompletableInput
            ).focus()

    async def action_save(self) -> None:
        app = self.app
        assert isinstance(app, TranscriberApp)
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
    """Fuzzy "jump to meeting" picker (U11, UX-OQ-1).

    The Meetings tab is the single canonical browsing/management surface; this modal only
    finds a meeting fast and jumps there. ``c: copy id`` stays — the picker is the one
    place a session UUID is retrievable by keyboard (U7).
    """

    BINDINGS = [
        Binding("escape", "close", "Close", show=True),
        Binding("c", "copy_id", "Copy ID", show=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._row_ids: list[str] = []
        self._filter = ""
        self._unsub: Callable[[], None] | None = None

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("Jump to meeting", classes="settings-title"),
            Input(placeholder="Type to filter (fuzzy)…", id="sessions-filter"),
            DataTable(id="sessions-table", cursor_type="row", zebra_stripes=True),
            Static("", id="sessions-empty", classes="dim"),
            Static("enter: open in Meetings   c: copy id   esc: close", classes="hint"),
            classes="settings-dialog",
        )

    def on_mount(self) -> None:
        app = self.app
        assert isinstance(app, TranscriberApp)
        table = self.query_one("#sessions-table", DataTable)
        table.add_columns("Title", "Started", "Ended")
        self._unsub = app.store.subscribe(self._on_store)
        self._on_store(app.store.get_state())
        self.query_one("#sessions-filter", Input).focus()

    def on_unmount(self) -> None:
        if self._unsub is not None:
            self._unsub()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "sessions-filter":
            return
        self._filter = event.value
        app = self.app
        assert isinstance(app, TranscriberApp)
        self._on_store(app.store.get_state())

    def _visible_rows(self, state: AppState) -> list[SessionRowState]:
        q = self._filter.strip().lower()
        if not q:
            return list(state.sessions_catalog)
        matched = [r for r in state.sessions_catalog if fuzzy_match(q, r.title)]
        # Substring hits above looser subsequence hits; stable within each group.
        matched.sort(key=lambda r: 0 if q in r.title.lower() else 1)
        return matched

    def _on_store(self, state: AppState) -> None:
        table = self.query_one("#sessions-table", DataTable)
        table.clear()
        self._row_ids.clear()
        for row in self._visible_rows(state):
            self._row_ids.append(row.id)
            ended = format_local_datetime(row.ended_at) if row.ended_at else "—"
            table.add_row(
                row.title[:56] + ("…" if len(row.title) > 56 else ""),
                format_local_datetime(row.started_at),
                ended,
                key=row.id,
            )
        # First-run/empty state: guide the user instead of showing an empty grid (U10);
        # a filter that matches nothing says so explicitly (U11).
        empty = self.query_one("#sessions-empty", Static)
        if not state.sessions_catalog:
            empty.update(SESSIONS_EMPTY_HINT)
        elif not self._row_ids:
            empty.update(f"No meeting matches “{self._filter.strip()}”.")
        else:
            empty.update("")

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

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "sessions-filter":
            return
        # Enter in the filter jumps to the best (first visible) match.
        if self._row_ids:
            self._jump(self._row_ids[0])

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.control.id != "sessions-table" or event.row_key.value is None:
            return
        self._jump(event.row_key.value)

    def _jump(self, sid: str) -> None:
        """Close the picker and open the meeting in the single home (Meetings tab)."""
        app = self.app
        assert isinstance(app, TranscriberApp)
        app.store.dispatch(act.SessionsScreenClosed(at=utc_now()))
        self.dismiss()
        app.query_one(TabbedContent).active = "tab-meetings"
        app.query_one("#meeting-browser", MeetingBrowser).select_session(UUID(sid))

    def action_close(self) -> None:
        app = self.app
        assert isinstance(app, TranscriberApp)
        app.store.dispatch(act.SessionsScreenClosed(at=utc_now()))
        self.dismiss()


class TranscriberApp(App[None]):
    """Textual front-end: renders from Store state only."""

    TITLE = "live-meeting-transcriber"
    # U4: only the core recording actions live in the always-visible footer; the
    # overflow actions stay key-bound (``show=False``) and are listed in the
    # command palette via ``get_system_commands``. Single source of truth:
    # ``footer_bindings.FOOTER_ACTIONS``.
    BINDINGS = [
        Binding(a.key, a.action, a.label, show=a.core, priority=a.priority) for a in FOOTER_ACTIONS
    ]

    CSS = """
    /* ---- global chrome ------------------------------------------------- */
    Screen { background: $background; }
    ModalScreen { align: center middle; }
    TabbedContent { height: 1fr; }
    TabPane { height: 1fr; padding: 0; }
    Tabs { background: $panel; }
    Footer { background: $panel; }

    /* ---- Live tab: hero transcript + card sidebar ----------------------- */
    #tab-live #main-row { height: 1fr; }
    #sidebar {
        width: 46; min-width: 46;
        padding: 1 1 0 1;
        overflow-y: auto;
    }
    .card {
        height: auto;
        border: round $primary 35%;
        border-title-color: $secondary;
        border-title-style: bold;
        padding: 0 1;
        margin-bottom: 1;
    }
    #transcript {
        border: round $accent 45%;
        border-title-color: $accent;
        border-title-style: bold;
        margin: 1 1 0 0;
        padding: 0 1;
        min-width: 40;
    }
    #transcript.-recording {
        border: round $error 70%;
        border-title-color: $error;
    }
    #live-details { height: auto; }
    .field-label { text-style: bold; color: $secondary; padding-top: 1; }
    #live-attendees-summary { padding: 0 0 0 1; }
    #live-notes { height: 7; min-height: 4; border: tall $primary 20%; }
    #notices { height: auto; padding: 0 1; text-style: italic; color: $success; }
    #errors { height: auto; max-height: 20; overflow-y: auto; padding: 0 1; }

    /* ---- Meetings tab ---------------------------------------------------- */
    #meeting-browser { height: 1fr; padding: 1 1 0 1; }
    #meeting-browser-split { height: 1fr; min-height: 8; }
    #meeting-list-pane { width: 48; min-width: 30; margin-right: 1; }
    #meeting-filter { margin-bottom: 0; }
    #finalize-jobs-panel {
        height: auto; max-height: 9;
        border: round $primary 35%;
        border-title-color: $secondary;
        border-title-style: bold;
        padding: 0 1;
        margin-top: 1;
        display: none;
    }
    #meeting-sessions-table {
        width: 1fr; height: 1fr;
        border: round $primary 35%;
        border-title-color: $secondary;
        border-title-style: bold;
    }
    #meeting-browser-detail {
        height: 1fr; min-height: 8;
        border: round $primary 35%;
        border-title-color: $secondary;
        border-title-style: bold;
        padding: 0 1;
    }
    #detail-tabs { margin-bottom: 1; }
    #detail-switcher { height: 1fr; }
    #detail-overview { height: 1fr; }
    #meeting-notes { height: 7; min-height: 4; max-height: 12; border: tall $primary 20%; }
    #meeting-summary { height: 1fr; min-height: 8; border: tall $primary 20%; }
    #meeting-transcript { height: 1fr; min-height: 8; border: tall $primary 20%; }
    .spk-row { height: auto; margin-bottom: 1; }
    .spk-label { width: 14; }
    .dim { text-style: dim; }

    /* ---- modal chrome ------------------------------------------------------ */
    .settings-dialog {
        padding: 1 2; width: 90; height: auto; max-height: 90%;
        background: $surface;
        border: round $primary;
        border-title-color: $accent;
    }
    .settings-title { text-style: bold; color: $accent; }
    .settings-edit { overflow-y: auto; }
    .settings-section { padding-top: 1; color: $secondary; }
    .settings-error { color: $error; height: auto; }
    .settings-switch-row { height: auto; }
    .settings-switch-row .switch-label { width: 1fr; padding: 1 0 0 1; }
    .hint { padding-top: 1; text-style: dim; }
    .help-dialog {
        padding: 1 2; width: 76; height: 90%; max-height: 90%;
        background: $surface;
        border: round $primary;
    }
    .help-scroll { height: 1fr; }
    #slide-preview-dialog { width: 95%; height: 90%; min-height: 28; max-width: 120; padding: 1 2; background: $surface; border: round $primary; layout: vertical; overflow: hidden; }
    #slide-preview-params { height: auto; max-height: 7; margin-bottom: 1; }
    #slide-preview-status { height: auto; max-height: 4; margin-bottom: 1; overflow-y: auto; }
    #slide-preview-split { height: 1fr; min-height: 12; }
    #slide-candidates-table { width: 1fr; min-width: 28; height: 1fr; min-height: 8; }
    #slide-image-pane { width: 1fr; min-width: 24; height: 1fr; min-height: 8; border: round $primary 35%; padding: 0 1; }
    #slide-preview-actions { dock: bottom; width: 100%; height: auto; padding-top: 1; background: $surface; }
    #slide-preview-actions Button { margin-right: 1; }
    #slide-preview-hint { dock: bottom; width: 100%; height: auto; padding-top: 1; background: $surface; }
    #sessions-table { height: 20; min-height: 8; }

    /* ---- Logs tab ------------------------------------------------------------ */
    #tab-logs { height: 1fr; }
    #logs-pane { padding: 1 1 0 1; }
    #ui-activity-log {
        height: 1fr; min-height: 10;
        border: round $primary 35%;
        border-title-color: $secondary;
        border-title-style: bold;
        padding: 0 1;
    }
    """

    def __init__(self, *, store: Store, container: Container, controller: TuiController) -> None:
        super().__init__()
        self.store = store
        self.container = container
        self._controller = controller
        self._last_segment_keys: tuple[tuple[str, str, str], ...] | None = None
        self._last_ui_log_len: int = 0
        # Inline Live-tab meeting fields (U23): which session's values are currently loaded
        # into the fields, and the last-persisted snapshot for change detection on auto-save.
        self._details_loaded_for: UUID | None = None
        self._last_saved_details: tuple[str, str, tuple[str, ...]] | None = None
        # B7: quit is deferred while a Speaker ID / finalize job is in flight so its
        # result gets persisted; a second quit press force-quits. The last toasted
        # finalize outcome is tracked so each result raises exactly one toast.
        self._quit_after_finalize: bool = False
        self._last_finalize_result_toasted: str | None = None

    def get_system_commands(self, screen: Screen[Any]) -> Iterable[SystemCommand]:
        """Keep the overflow actions (hidden from the trimmed footer, U4)
        discoverable by listing them in the command palette alongside the
        built-in commands. Each entry runs the same action as its key binding.
        """
        yield from super().get_system_commands(screen)
        for action in overflow_footer_actions():
            yield SystemCommand(
                action.label,
                f"{action.key} — {action.label}",
                functools.partial(self.run_action, action.action),
            )

    def compose(self) -> ComposeResult:
        yield StatusDeck(store=self.store)
        with TabbedContent(initial="tab-live"):
            with TabPane("Live", id="tab-live"), Horizontal(id="main-row"):
                with Vertical(id="sidebar"):
                    with Vertical(id="live-details", classes="card"):
                        yield Static("Title", classes="field-label")
                        yield TabCompletableInput(
                            placeholder="Meeting title", id="live-title", disabled=True
                        )
                        yield Static("Attendees [dim](comma-separated)[/]", classes="field-label")
                        yield TabCompletableInput(
                            placeholder="Alice, Bob, …",
                            id="live-attendees",
                            disabled=True,
                        )
                        yield Static("", id="live-attendees-summary", classes="dim")
                        yield Static("Notes", classes="field-label")
                        yield TextArea(id="live-notes", disabled=True)
                    yield Static("", id="status-session", classes="card")
                    yield Static("", id="status-audio", classes="card")
                    yield Static("", id="status-pipeline", classes="card")
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

    def action_help(self) -> None:
        # U16: guard against stacking duplicate overlays if `?` is pressed twice.
        if isinstance(self.screen, HelpScreen):
            return
        self.push_screen(HelpScreen())

    async def on_mount(self) -> None:
        self.register_theme(NOTETAKER_DARK)
        self.theme = NOTETAKER_DARK.name
        self.store.subscribe(self._on_state)
        self.query_one(
            "#live-attendees", TabCompletableInput
        ).suggester = CommaSeparatedPeopleSuggester(self.container.people)
        self.query_one("#live-details").border_title = "meeting · saves automatically"
        self.query_one("#status-session").border_title = "session"
        self.query_one("#status-audio").border_title = "audio"
        self.query_one("#status-pipeline").border_title = "pipeline"
        self.query_one("#transcript").border_title = "live transcript"
        self.query_one("#ui-activity-log").border_title = "console"
        self._update_attendees_summary("")
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
        dual_path_reason = dual_path_downgrade_reason(
            audio_stereo_mode=self.container.settings.audio_stereo_mode,
            audio_channels=self.container.settings.audio_channels,
            transcriber=self.container.transcriber,
        )
        if dual_path_reason is not None:
            self.store.dispatch(act.WarningRaised(message=dual_path_reason, at=utc_now()))

    def _tick_elapsed(self) -> None:
        state = self.store.get_state()
        if not select_is_recording(state):
            return
        try:
            self._render_status_cards(state)
        except NoMatches:
            # Main screen not mounted (a modal is up or teardown) — skip; re-renders next tick.
            return

    def _on_state(self, state: AppState) -> None:
        self._maybe_toast_finalize_result(state)
        try:
            notices = self.query_one("#notices", Static)
            err_panel = self.query_one("#errors", Static)
            log = self.query_one("#transcript", RichLog)
            self._render_status_cards(state)
        except NoMatches:
            # Main screen isn't mounted (app shutting down, or a modal screen is active).
            # State updates dispatched during teardown — e.g. background finalize progress —
            # can arrive after the widgets are gone; skip rendering (a live app re-renders
            # on the next dispatch).
            return

        self._sync_live_details(state)
        # The transcript border shifts to the recording signal color while live.
        log.set_class(select_is_recording(state), "-recording")
        if state.notices:
            notices.update(
                Text.from_markup(
                    "[bold]Last actions[/]\n" + "\n".join(f"• {n}" for n in state.notices[-4:])
                )
            )
        else:
            notices.update(
                Text.from_markup(
                    "[dim]w: export · k: summarize · ctrl+d: speaker ID · ctrl+3: logs[/]"
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
                log.write(self._transcript_block(state, line))
        elif old_keys != new_keys:
            log.clear()
            if not state.recent_transcript_segments:
                # First-run / emptied transcript: show a guidance line instead of a
                # blank pane (U10). Replaced as soon as real segments arrive.
                log.write(Text.from_markup(LIVE_EMPTY_HINT))
            for line in state.recent_transcript_segments:
                log.write(self._transcript_block(state, line))
        self._last_segment_keys = new_keys

    @staticmethod
    def _transcript_block(state: AppState, line: TranscriptLineState) -> Text:
        return transcript_segment_text(
            timestamp=select_transcript_timestamp(line),
            speaker_label=select_display_speaker(state, line.speaker),
            speaker_key=line.speaker,
            body=line.text,
        )

    def _render_status_cards(self, state: AppState) -> None:
        """Render the three sidebar cards (session / audio / pipeline)."""
        now = utc_now()

        def _group(lines: list[str]) -> Group:
            return Group(*[Text.from_markup(x) for x in lines])

        self.query_one("#status-session", Static).update(
            _group(build_session_card_lines(state, now))
        )
        self.query_one("#status-audio", Static).update(_group(build_audio_card_lines(state, now)))
        self.query_one("#status-pipeline", Static).update(
            _group(build_pipeline_card_lines(state, utc_now()))
        )

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

    def _sync_live_details(self, state: AppState) -> None:
        """Keep the inline Live-tab meeting fields (U23) in step with the current session.

        Fields load their values **once** per session (when ``current_session_id`` changes) so
        that per-second elapsed ticks and per-segment renders never overwrite what the user is
        typing; a focused field is never clobbered even on that first load.
        """
        try:
            title = self.query_one("#live-title", TabCompletableInput)
            attendees = self.query_one("#live-attendees", TabCompletableInput)
            notes = self.query_one("#live-notes", TextArea)
        except NoMatches:
            return

        sid = state.current_session_id
        if sid is None:
            if self._details_loaded_for is not None:
                self._details_loaded_for = None
                self._last_saved_details = None
                title.value = ""
                attendees.value = ""
                notes.text = ""
                self._update_attendees_summary("")
            title.disabled = attendees.disabled = notes.disabled = True
            return

        title.disabled = attendees.disabled = notes.disabled = False
        if sid == self._details_loaded_for:
            return
        session = self.container.sessions.get(sid)
        if session is None:
            return
        if title is not self.focused:
            title.value = session.title
        if attendees is not self.focused:
            attendees.value = ", ".join(session.attendees)
        if notes is not self.focused:
            notes.text = session.notes
        self._update_attendees_summary(", ".join(session.attendees))
        self._details_loaded_for = sid
        self._last_saved_details = (session.title, session.notes, tuple(session.attendees))

    def _update_attendees_summary(self, raw: str) -> None:
        """Render the live 'who's in the room' chip line under the attendees field (U24)."""
        try:
            summary = self.query_one("#live-attendees-summary", Static)
        except NoMatches:
            return
        names = [p.strip() for p in raw.replace("\n", ",").split(",") if p.strip()]
        if names:
            summary.update(Text.from_markup("[dim]→ " + " · ".join(names) + "[/]"))
        else:
            summary.update(Text.from_markup("[dim]no attendees yet[/]"))

    async def _save_live_details(self) -> None:
        """Persist the inline Live-tab fields for the current session (U23).

        Auto-save with no button: reused by Enter (``on_input_submitted``), blur
        (``on_descendant_blur``) and the stop flush. Blank titles are skipped silently
        (``update_details`` would otherwise raise), and an unchanged snapshot is a no-op so
        blur/tick storms don't hammer the DB.
        """
        sid = self.store.get_state().current_session_id
        if sid is None:
            return
        try:
            title = self.query_one("#live-title", TabCompletableInput).value.strip()
            raw_attendees = self.query_one("#live-attendees", TabCompletableInput).value
            notes = self.query_one("#live-notes", TextArea).text
        except NoMatches:
            return
        if not title:
            return
        parts = [p.strip() for p in raw_attendees.replace("\n", ",").split(",")]
        attendees = [p for p in parts if p]
        snapshot = (title, notes, tuple(attendees))
        if snapshot == self._last_saved_details:
            return
        self._last_saved_details = snapshot
        await self.store.dispatch_with_effects(
            act.SessionDetailsCommitRequested(
                session_id=sid,
                title=title,
                notes=notes,
                attendees=attendees,
                at=utc_now(),
            )
        )
        for name in attendees:
            self.container.people.touch(name)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "live-attendees":
            self._update_attendees_summary(event.value)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id in ("live-title", "live-attendees"):
            await self._save_live_details()

    async def on_descendant_blur(self, event: events.DescendantBlur) -> None:
        if getattr(event.widget, "id", None) in ("live-title", "live-attendees", "live-notes"):
            await self._save_live_details()

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
        # Flush any in-progress inline edits (notes typed then immediately stopped) before
        # tearing the recording down (U23).
        await self._save_live_details()
        await self.store.dispatch_with_effects(act.RecordingStopRequested(at=utc_now()))

    def action_name_speakers(self) -> None:
        """Name detected speakers for the current live meeting (Live tab).

        Title / context / attendees are edited inline on the Live tab (U23), so this modal
        is speaker-naming only.
        """
        state = self.store.get_state()
        sid = state.current_session_id
        if sid is None:
            self.notify("Start (or resume) a meeting on the Live tab first.", severity="warning")
            return
        self.push_screen(
            NameSpeakersScreen(
                str(sid),
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
        self.notify(meeting_actions.SPEAKER_ID_STARTED_NOTICE, severity="information")
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

    def _maybe_toast_finalize_result(self, state: AppState) -> None:
        """Raise one toast per finalize outcome (B7).

        The persistent surfaces are the status deck, the Live-tab notices and the
        Logs tab; the toast is the attention-grabber that works from any tab or
        modal. Runs before widget queries so a pushed screen can't swallow it.
        """
        result = state.finalize_last_result
        if not result or result == self._last_finalize_result_toasted:
            return
        self._last_finalize_result_toasted = result
        if state.finalize_last_result_level == "error":
            self.notify(result, severity="error", timeout=10)
        elif state.finalize_last_result_level == "warning":
            self.notify(result, severity="warning", timeout=10)
        else:
            self.notify(result, severity="information", timeout=10)

    async def action_quit(self) -> None:
        if self._quit_after_finalize:
            # Second press: the operator insists — force-quit. The in-flight job's
            # result is lost, but startup recovery re-queues it next launch.
            self.exit()
            return
        await self.store.dispatch_with_effects(act.RecordingStopRequested(at=utc_now()))
        if self._controller.finalize_busy:
            # B7: exiting now would cancel the finalize worker between the WhisperX
            # pass and the DB write — the shutdown still blocks on the compute
            # thread, so the wait costs nothing extra but keeps the result.
            self._quit_after_finalize = True
            msg = (
                "Speaker ID / finalize is still running — quitting once it saves. "
                "Press q again to discard the result and quit (the job re-runs on next launch; "
                "exit may still take a moment while the compute thread winds down)."
            )
            self.notify(msg, severity="warning", timeout=12)
            self.store.dispatch(act.NoticeRaised(message=msg, at=utc_now()))
            self.run_worker(self._exit_when_finalize_idle(), exclusive=False)
            return
        self.exit()

    async def _exit_when_finalize_idle(self) -> None:
        await self._controller.wait_finalize_idle()
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
