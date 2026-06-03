"""Inventory on-disk media for a session (WAV chunks, slides, exports)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from live_meeting_transcriber.application.video_session_storage import (
    read_source_media_video_path,
    session_slides_dir,
)
from live_meeting_transcriber.audio.session_recording import full_session_wav_path


@dataclass(frozen=True)
class MediaFileEntry:
    path: Path
    size_bytes: int


@dataclass(frozen=True)
class SessionMediaInventory:
    """Existing files only; empty sections mean nothing on disk yet."""

    chunk_wavs: tuple[MediaFileEntry, ...] = ()
    full_session_wav: MediaFileEntry | None = None
    slide_images: tuple[MediaFileEntry, ...] = ()
    export_screenshots: tuple[MediaFileEntry, ...] = ()
    export_markdown: tuple[Path, ...] = ()
    source_video: MediaFileEntry | None = None

    @property
    def has_any(self) -> bool:
        return bool(
            self.chunk_wavs
            or self.full_session_wav
            or self.slide_images
            or self.export_screenshots
            or self.export_markdown
            or self.source_video
        )


def _file_entry(path: Path) -> MediaFileEntry | None:
    if not path.is_file():
        return None
    return MediaFileEntry(path=path.resolve(), size_bytes=path.stat().st_size)


def _list_wavs(directory: Path) -> tuple[MediaFileEntry, ...]:
    if not directory.is_dir():
        return ()
    entries: list[MediaFileEntry] = []
    for wav in sorted(directory.glob("*.wav")):
        entry = _file_entry(wav)
        if entry is not None:
            entries.append(entry)
    return tuple(entries)


def _list_images(directory: Path) -> tuple[MediaFileEntry, ...]:
    if not directory.is_dir():
        return ()
    entries: list[MediaFileEntry] = []
    for pattern in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
        for img in sorted(directory.glob(pattern)):
            entry = _file_entry(img)
            if entry is not None:
                entries.append(entry)
    return tuple(entries)


def collect_session_media(data_dir: Path, session_id: UUID) -> SessionMediaInventory:
    """Scan known artifact locations; paths that do not exist are omitted."""
    sid = str(session_id)
    root = data_dir.resolve()
    chunks_dir = (root / "chunks" / sid).resolve()
    session_dir = (root / "sessions" / sid).resolve()

    full_wav = _file_entry(full_session_wav_path(session_dir))
    slides_dir = session_slides_dir(root, session_id)
    export_shots = (root / "exports" / "screenshots" / sid).resolve()

    export_md: list[Path] = []
    exports_dir = (root / "exports").resolve()
    if exports_dir.is_dir():
        for md in sorted(exports_dir.glob(f"{sid}_*.md")):
            if md.is_file():
                export_md.append(md.resolve())

    source_video: MediaFileEntry | None = None
    try:
        video_path = read_source_media_video_path(root, session_id)
        source_video = _file_entry(video_path)
    except Exception:
        source_video = None

    return SessionMediaInventory(
        chunk_wavs=_list_wavs(chunks_dir),
        full_session_wav=full_wav,
        slide_images=_list_images(slides_dir),
        export_screenshots=_list_images(export_shots),
        export_markdown=tuple(export_md),
        source_video=source_video,
    )


def format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def format_session_media_inventory(inventory: SessionMediaInventory) -> str:
    """Plain-text lines for TUI display (paths only, no transcript content)."""
    if not inventory.has_any:
        return "No media files found for this session on disk."

    lines: list[str] = []

    def _section(title: str, entries: tuple[MediaFileEntry, ...] | MediaFileEntry | None) -> None:
        if isinstance(entries, MediaFileEntry):
            items = (entries,)
        elif entries:
            items = entries
        else:
            return
        lines.append(f"[bold]{title}[/bold]")
        for item in items:
            lines.append(f"  {item.path}  ({format_size(item.size_bytes)})")
        lines.append("")

    _section("Chunk WAVs", inventory.chunk_wavs)
    _section("Full session", inventory.full_session_wav)
    _section("Slides", inventory.slide_images)
    _section("Export screenshots", inventory.export_screenshots)
    if inventory.export_markdown:
        lines.append("[bold]Export markdown[/bold]")
        for path in inventory.export_markdown:
            lines.append(f"  {path}")
        lines.append("")
    _section("Source video", inventory.source_video)

    return "\n".join(lines).rstrip()
