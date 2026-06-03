"""TUI modal and runner for importing a video file or URL."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static

from live_meeting_transcriber.application.container import Container
from live_meeting_transcriber.application.video_import_service import (
    VideoImportError,
    VideoImportProgress,
    VideoImportResult,
    VideoImportService,
)
from live_meeting_transcriber.transcription.faster_whisper_transcriber import (
    FasterWhisperTranscriptionError,
)
from live_meeting_transcriber.transcription.openai_transcriber import OpenAITranscriptionError


@dataclass(frozen=True)
class VideoImportForm:
    source: str
    title: str | None


class VideoImportModal(ModalScreen[VideoImportForm | None]):
    """Collect local path or http(s) URL for ``VideoImportService``."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True, priority=True),
        Binding("ctrl+enter,ctrl+return", "submit", "Import", show=True, priority=True),
    ]

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("Import video", classes="settings-title"),
            Static(
                "Local MP4 path or http(s) URL (YouTube etc.; URLs need yt-dlp).\n"
                "Transcription runs now; use [bold]p[/] slide preview after import.\n"
                "Ctrl+Enter: import · Esc: cancel — or use buttons below.",
                classes="dim",
            ),
            Static("Source path or URL"),
            Input(placeholder="/path/to/talk.mp4 or https://…", id="video-import-source"),
            Static("Title (optional)"),
            Input(placeholder="Defaults to filename or page title", id="video-import-title"),
            Horizontal(
                Button("Import", id="video-import-submit", variant="primary"),
                Button("Cancel", id="video-import-cancel"),
            ),
            classes="settings-dialog",
        )

    def on_mount(self) -> None:
        self.query_one("#video-import-source", Input).focus()

    def action_submit(self) -> None:
        source = self.query_one("#video-import-source", Input).value.strip()
        if not source:
            self.app.notify("Enter a file path or URL.", severity="warning")
            return
        title_raw = self.query_one("#video-import-title", Input).value.strip()
        self.dismiss(VideoImportForm(source=source, title=title_raw or None))

    def action_cancel(self) -> None:
        self.dismiss(None)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "video-import-submit":
            self.action_submit()
        elif event.button.id == "video-import-cancel":
            self.action_cancel()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "video-import-source":
            title_inp = self.query_one("#video-import-title", Input)
            if not title_inp.value.strip():
                title_inp.focus()
                return
        self.action_submit()


async def run_video_import(
    container: Container,
    *,
    source: str,
    title: str | None = None,
    on_progress: Callable[[VideoImportProgress], None] | None = None,
) -> VideoImportResult:
    """Import and transcribe a video; slides are reviewed later via slide preview."""
    svc = VideoImportService(
        settings=container.settings,
        sessions=container.sessions,
        transcripts=container.transcripts,
        transcriber=container.transcriber,
    )
    return await svc.import_video(
        source=source,
        title=title,
        extract_slides=False,
        on_progress=on_progress,
    )


def format_video_import_error(exc: BaseException) -> str:
    if isinstance(exc, VideoImportError):
        return str(exc)
    if isinstance(exc, (OpenAITranscriptionError, FasterWhisperTranscriptionError)):
        return str(exc)
    return f"Video import failed: {exc}"
