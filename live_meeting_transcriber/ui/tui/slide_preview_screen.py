"""TUI screen for slide detection preview and parameter tuning."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import Focus
from textual.screen import ModalScreen
from textual.widgets import Button, Collapsible, DataTable, Input, Select, Static

from live_meeting_transcriber.application.container import Container
from live_meeting_transcriber.application.slide_preview_service import (
    SlidePreviewError,
    SlidePreviewResult,
    SlidePreviewService,
)
from live_meeting_transcriber.application.slide_review import format_timestamp
from live_meeting_transcriber.domain.models import SlideCandidate
from live_meeting_transcriber.ui.tui.slide_preview_helpers import (
    accepted_candidates,
    build_slide_params,
    format_candidate_label,
    image_widget_class,
    inline_image_unsupported_message,
    normalize_strategy,
    open_image_externally,
    slide_detection_help_text,
    slide_param_focus_hint,
    terminal_supports_inline_images,
    try_chafa_ascii_preview,
)


class SlideImagePane(Vertical):
    """Inline PNG preview (textual-image) or path fallback."""

    DEFAULT_CSS = """
    #slide-preview-image { width: 100%; height: 1fr; min-height: 10; }
    #slide-preview-fallback { width: 100%; height: auto; min-height: 6; }
    """

    def __init__(self) -> None:
        super().__init__(id="slide-image-pane")
        self._image_widget: Static | None = None
        self._fallback: Static | None = None
        self._current_path: Path | None = None

    def compose(self) -> ComposeResult:
        cls = image_widget_class()
        if cls is not None and terminal_supports_inline_images():
            self._image_widget = cls(id="slide-preview-image")
            yield self._image_widget
        self._fallback = Static(
            "[dim]No preview — run detection or select a candidate.[/]",
            id="slide-preview-fallback",
        )
        yield self._fallback

    def on_mount(self) -> None:
        if self._image_widget is not None and self._fallback is not None:
            self._fallback.display = False
        elif self._fallback is not None and not terminal_supports_inline_images():
            self._fallback.update(inline_image_unsupported_message())

    def show_path(self, path: Path | None) -> None:
        self._current_path = path
        if path is None or not path.is_file():
            if self._image_widget is not None:
                self._image_widget.display = False
            if self._fallback is not None:
                self._fallback.display = True
                self._fallback.update("[dim]No preview image for this candidate.[/]")
            return

        if self._image_widget is not None:
            self._image_widget.display = True
            self._image_widget.image = str(path)  # type: ignore[attr-defined]
            if self._fallback is not None:
                self._fallback.display = False
                self._fallback.update("")
            return

        if self._fallback is not None:
            self._fallback.display = True
            lines = [
                f"[bold]{path.name}[/bold]",
                f"[dim]{path}[/dim]",
                "",
            ]
            if not terminal_supports_inline_images():
                lines.append(inline_image_unsupported_message())
            else:
                lines.append(
                    "[dim]Install optional extra[/] [bold]tui-image[/] "
                    "[dim]for inline preview ·[/] [bold]o[/] open externally[/]"
                )
            ascii_preview = try_chafa_ascii_preview(path)
            if ascii_preview:
                lines.extend(["", ascii_preview])
            self._fallback.update("\n".join(lines))

    @property
    def current_path(self) -> Path | None:
        return self._current_path


class SlidePreviewScreen(ModalScreen[None]):
    """Re-run slide detection with tunable params; review candidates before apply."""

    DEFAULT_CSS = """
    #slide-preview-dialog { width: 95%; height: 90%; max-width: 120; }
    #slide-preview-params { height: auto; margin-bottom: 1; }
    #slide-preview-params Input { width: 1fr; min-width: 8; }
    #slide-preview-params Select { width: 1fr; min-width: 14; }
    #slide-preview-status { height: auto; margin-bottom: 1; }
    #slide-preview-split { height: 1fr; min-height: 12; }
    #slide-candidates-table { width: 1fr; min-width: 28; height: 1fr; }
    #slide-image-pane { width: 1fr; min-width: 24; height: 1fr; border: solid $boost; padding: 0 1; }
    #slide-preview-hint { height: auto; padding-top: 1; }
    #slide-param-hint { height: auto; margin-bottom: 1; }
    #slide-help-panel { height: auto; max-height: 12; margin-bottom: 1; }
    """

    BINDINGS = [
        Binding("escape", "close", "Close", show=True, priority=True),
        Binding("r", "run_preview", "Re-run", show=True, priority=True),
        Binding("y,Y", "keep_candidate", "Keep", show=True, priority=True),
        Binding("n,N", "reject_candidate", "Skip", show=True, priority=True),
        Binding("a", "apply_slides", "Apply", show=True, priority=True),
        Binding("o,O", "open_external", "Open", show=True, priority=True),
    ]

    def __init__(self, *, container: Container, session_id: UUID) -> None:
        super().__init__()
        self._container = container
        self._session_id = session_id
        self._result: SlidePreviewResult | None = None
        self._review: dict[int, bool | None] = {}
        self._busy = False

    def compose(self) -> ComposeResult:
        s = self._container.settings
        params = s.slide_detection_params()
        yield Vertical(
            Static("Slide preview & tune", classes="settings-title"),
            Static(
                f"Session [dim]{self._session_id}[/dim] — detection only (no re-transcribe)",
                classes="dim",
            ),
            Horizontal(
                Vertical(
                    Static("Strategy", classes="dim"),
                    Select(
                        [(label, label) for label in ("frame_diff", "ffmpeg_scene")],
                        value=s.video_slide_strategy,
                        id="slide-strategy",
                    ),
                    id="slide-strategy-col",
                ),
                Vertical(
                    Static("Sample (s)", classes="dim"),
                    Input(str(params.sample_interval_seconds), id="slide-sample"),
                ),
                Vertical(
                    Static("Threshold", classes="dim"),
                    Input(str(params.change_threshold), id="slide-threshold"),
                ),
                Vertical(
                    Static("Min interval (s)", classes="dim"),
                    Input(str(params.min_slide_interval_seconds), id="slide-min-interval"),
                ),
                Vertical(
                    Static("Max candidates", classes="dim"),
                    Input(str(params.max_candidates), id="slide-max-candidates"),
                ),
                Button("Run preview", id="slide-run-btn", variant="primary"),
                id="slide-preview-params",
            ),
            Static(
                "Threshold: lower = more sensitive · Min interval: min seconds between slides",
                classes="dim",
            ),
            Static(
                "Focus a field for a short hint.",
                id="slide-param-hint",
                classes="dim",
            ),
            Collapsible(
                Static(slide_detection_help_text(), id="slide-help-body"),
                title="? Slide detection help",
                collapsed=True,
                id="slide-help-panel",
            ),
            Static(
                "Adjust parameters and press Run preview or [bold]r[/].", id="slide-preview-status"
            ),
            Horizontal(
                DataTable(id="slide-candidates-table", cursor_type="row", zebra_stripes=True),
                SlideImagePane(),
                id="slide-preview-split",
            ),
            Static(
                "[dim]↑↓[/] select · [dim]y[/]/[dim]n[/] keep/skip · [dim]a[/] apply kept · "
                "[dim]o[/] open image · [dim]r[/] re-run · [dim]Esc[/] close",
                id="slide-preview-hint",
                classes="hint",
            ),
            id="slide-preview-dialog",
            classes="settings-dialog",
        )

    def on_mount(self) -> None:
        self.call_after_refresh(self._init_preview_ui)

    def _init_preview_ui(self) -> None:
        if not self.is_mounted:
            return
        table = self._get_candidates_table()
        if table is None:
            return
        table.add_columns("Candidate", "Time", "Score", "Keep")
        self.run_worker(self._run_preview(), exclusive=True)

    def _get_candidates_table(self) -> DataTable | None:
        if not self.is_mounted:
            return None
        for node in self.query("#slide-candidates-table"):
            if isinstance(node, DataTable):
                return node
        return None

    def _read_strategy(self) -> str:
        select = self.query_one("#slide-strategy", Select)
        return str(select.value)

    def _read_params(self):
        return build_slide_params(
            sample_interval=self.query_one("#slide-sample", Input).value,
            threshold=self.query_one("#slide-threshold", Input).value,
            min_interval=self.query_one("#slide-min-interval", Input).value,
            max_candidates=self.query_one("#slide-max-candidates", Input).value,
            settings=self._container.settings,
        )

    def _set_busy(self, busy: bool) -> None:
        if not self.is_mounted:
            return
        self._busy = busy
        for node_id in (
            "#slide-strategy",
            "#slide-sample",
            "#slide-threshold",
            "#slide-min-interval",
            "#slide-max-candidates",
            "#slide-run-btn",
        ):
            self.query_one(node_id).disabled = busy

    def _update_status(self, message: str) -> None:
        if not self.is_mounted:
            return
        self.query_one("#slide-preview-status", Static).update(message)

    async def _run_preview(self) -> None:
        if self._busy:
            return
        self._set_busy(True)
        self._update_status("[dim]Detecting slides…[/]")
        self.app.notify("Detecting slides…", severity="information", timeout=4)
        try:
            strategy = normalize_strategy(self._read_strategy(), settings=self._container.settings)
            params = self._read_params()
        except ValueError as e:
            self._set_busy(False)
            self.app.notify(f"Invalid parameter: {e}", severity="error")
            self._update_status("Fix parameter values and press [bold]r[/] to retry.")
            return

        svc = SlidePreviewService(
            settings=self._container.settings,
            sessions=self._container.sessions,
        )
        try:
            result = await svc.preview(
                session_id=self._session_id,
                strategy=strategy,
                params=params,
            )
        except SlidePreviewError as e:
            self._set_busy(False)
            self.app.notify(str(e), severity="error")
            self._update_status(f"[red]{e}[/] — needs imported source video for this session.")
            return

        if not self.is_mounted:
            return

        self._result = result
        self._review = {i: None for i in range(len(result.candidates))}
        self._refresh_table()
        self._set_busy(False)
        kept = sum(1 for v in self._review.values() if v is True)
        n = len(result.candidates)
        self.app.notify(f"Found {n} slide candidate(s).", severity="information", timeout=5)
        self._update_status(
            f"[bold]Found {n} candidate(s)[/] · strategy [bold]{result.strategy}[/] · "
            f"duration {result.duration_seconds:.0f}s · kept {kept} · "
            "use table for timestamps"
        )
        table = self._get_candidates_table()
        if result.candidates:
            if table is not None:
                table.move_cursor(row=0)
                self._show_candidate(0)
        elif self.is_mounted:
            self.query_one(SlideImagePane).show_path(None)

    def _refresh_table(self) -> None:
        table = self._get_candidates_table()
        if table is None:
            return
        table.clear()
        if self._result is None:
            return
        for i, cand in enumerate(self._result.candidates):
            keep = self._review.get(i)
            mark = "✓" if keep is True else ("✗" if keep is False else "·")
            table.add_row(
                str(i + 1),
                format_timestamp(cand.timestamp_seconds),
                f"{cand.change_score:.2f}",
                mark,
                key=str(i),
            )

    def _selected_index(self) -> int | None:
        table = self._get_candidates_table()
        if table is None:
            return None
        coord = table.cursor_coordinate
        if coord is None or coord.row < 0:
            return None
        if self._result is None or coord.row >= len(self._result.candidates):
            return None
        return coord.row

    def _show_candidate(self, index: int) -> None:
        if self._result is None or index < 0 or index >= len(self._result.candidates):
            self.query_one(SlideImagePane).show_path(None)
            return
        cand = self._result.candidates[index]
        pane = self.query_one(SlideImagePane)
        pane.show_path(cand.preview_path)
        label = format_candidate_label(index, cand, keep=self._review.get(index))
        self._update_status(
            f"{label} · strategy [bold]{self._result.strategy}[/] · "
            f"{len(self._result.candidates)} total"
        )

    async def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.control.id != "slide-candidates-table":
            return
        idx = self._selected_index()
        if idx is not None:
            self._show_candidate(idx)

    def on_focus(self, event: Focus) -> None:
        node = event.control
        if node.id and node.id in (
            "slide-strategy",
            "slide-sample",
            "slide-threshold",
            "slide-min-interval",
            "slide-max-candidates",
        ):
            self.query_one("#slide-param-hint", Static).update(slide_param_focus_hint(node.id))

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "slide-run-btn":
            self.run_worker(self._run_preview(), exclusive=True)

    async def action_run_preview(self) -> None:
        self.run_worker(self._run_preview(), exclusive=True)

    async def action_keep_candidate(self) -> None:
        idx = self._selected_index()
        if idx is None:
            self.app.notify("Select a candidate row first.", severity="warning")
            return
        self._review[idx] = True
        self._refresh_table()
        table = self._get_candidates_table()
        if table is not None:
            table.move_cursor(row=idx)
        self._show_candidate(idx)

    async def action_reject_candidate(self) -> None:
        idx = self._selected_index()
        if idx is None:
            self.app.notify("Select a candidate row first.", severity="warning")
            return
        self._review[idx] = False
        self._refresh_table()
        table = self._get_candidates_table()
        if table is not None:
            table.move_cursor(row=idx)
        self._show_candidate(idx)

    async def action_open_external(self) -> None:
        pane = self.query_one(SlideImagePane)
        path = pane.current_path
        if path is None:
            idx = self._selected_index()
            if idx is not None and self._result is not None:
                path = self._result.candidates[idx].preview_path
        if path is None or not path.is_file():
            self.app.notify("No preview image for this candidate.", severity="warning")
            return
        if not open_image_externally(path):
            self.app.notify("No external viewer (xdg-open) found.", severity="error")
            return
        self.app.notify(f"Opened {path.name}")

    async def action_apply_slides(self) -> None:
        if self._result is None or not self._result.candidates:
            self.app.notify("Run preview first.", severity="warning")
            return
        accepted = accepted_candidates(self._result.candidates, self._review)
        if not accepted:
            self.app.notify("Mark slides to keep with [bold]y[/] before apply.", severity="warning")
            return
        self._set_busy(True)
        self._update_status(f"[dim]Saving {len(accepted)} slide(s)…[/]")
        try:
            saved = await self._apply_accepted(accepted)
        except SlidePreviewError as e:
            self.app.notify(str(e), severity="error")
            return
        finally:
            self._set_busy(False)
        if saved:
            self.app.notify(f"Saved {saved} slide(s) to sessions/{self._session_id}/slides/")
            self._update_status(f"Applied {saved} slide(s). Press [bold]Esc[/] to close.")

    async def _apply_accepted(self, accepted: list[SlideCandidate]) -> int:
        svc = SlidePreviewService(
            settings=self._container.settings,
            sessions=self._container.sessions,
        )
        return await svc.apply(
            session_id=self._session_id,
            candidates=accepted,
            accept_all=True,
        )

    def action_close(self) -> None:
        self.dismiss()
