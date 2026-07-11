"""Dual meeting export: plain markdown under the app data dir + optional vault note.

Application-owned orchestration (A9): screenshot collection, overwrite policy and file
writes happen here; the vault-specific note rendering/naming is delegated to the
``MeetingNoteRenderer`` port (implemented by the Obsidian adapter and wired by callers).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from live_meeting_transcriber.application.export_markdown import (
    build_session_export_markdown,
    export_filename_for_session,
)
from live_meeting_transcriber.application.export_overwrite import (
    ExportOverwriteConfirm,
    ExportWriteDecision,
    resolve_export_write,
    write_text_from_decision,
)
from live_meeting_transcriber.application.screenshot_export import (
    ScreenshotHit,
    copy_screenshot_for_export,
    list_session_screenshots,
    markdown_image_line,
    merge_transcript_lines_with_screenshots,
)
from live_meeting_transcriber.domain.exceptions import ExportCancelledError
from live_meeting_transcriber.domain.models import MeetingSession, Summary, TranscriptSegment
from live_meeting_transcriber.domain.ports import MeetingNoteRenderer
from live_meeting_transcriber.domain.speaker_display import format_transcript_speaker_label


@dataclass(frozen=True)
class DualExportResult:
    app_path: Path
    obs_path: Path | None
    app_written: bool
    obs_written: bool
    skipped_identical: tuple[Path, ...] = ()


@dataclass(frozen=True)
class DualExportPrepared:
    app_path: Path
    app_content: str
    obs_path: Path | None
    obs_content: str | None


def _write_export_content(
    path: Path,
    content: str,
    *,
    confirm_overwrite: ExportOverwriteConfirm | None,
) -> tuple[bool, ExportWriteDecision]:
    decision = resolve_export_write(path, content, confirm_overwrite=confirm_overwrite)
    if decision == ExportWriteDecision.cancelled:
        raise ExportCancelledError(path)
    write_text_from_decision(path, content, decision)
    return decision == ExportWriteDecision.write, decision


def prepare_dual_export(
    *,
    app_base_dir: Path,
    session: MeetingSession,
    segments: list[TranscriptSegment],
    summary: Summary | None,
    speaker_display: dict[str, str] | None,
    note_renderer: MeetingNoteRenderer | None,
    screenshots_source_dir: Path | None = None,
    obsidian_screenshots_dir: Path | None = None,
) -> DualExportPrepared:
    """Build export paths and markdown without writing the markdown files."""
    disp = speaker_display or {}
    hits = list_session_screenshots(
        screenshots_source_dir, session, segments, data_dir=app_base_dir
    )
    app_exports_dir = (app_base_dir / "exports").resolve()
    app_link_by_source: dict[Path, str] = {}
    obs_link_by_source: dict[Path, str] = {}

    if hits:
        shot_sub = app_exports_dir / "screenshots" / str(session.id)
        for i, h in enumerate(hits):
            dest = copy_screenshot_for_export(
                h.source_path,
                shot_sub,
                session_id=session.id,
                captured_utc=h.captured_utc,
                index=i,
            )
            app_link_by_source[h.source_path] = Path(
                os.path.relpath(dest, app_exports_dir)
            ).as_posix()

    obs_meeting_path: Path | None = None
    if note_renderer is not None:
        obs_meeting_path = note_renderer.note_path(session)

    obs_shot_dir = obsidian_screenshots_dir
    if hits and obs_meeting_path is not None:
        assert note_renderer is not None
        if obs_shot_dir is None:
            obs_shot_dir = note_renderer.screenshots_dir(obs_meeting_path)
        obs_shot_dir.mkdir(parents=True, exist_ok=True)
        for i, h in enumerate(hits):
            dest = copy_screenshot_for_export(
                h.source_path,
                obs_shot_dir,
                session_id=session.id,
                captured_utc=h.captured_utc,
                index=i,
            )
            obs_link_by_source[h.source_path] = Path(
                os.path.relpath(dest, obs_meeting_path.parent)
            ).as_posix()

    def app_speaker_line(seg: TranscriptSegment) -> str:
        label = format_transcript_speaker_label(seg.speaker, disp)
        return f"- [{seg.started_at.isoformat()}] {label}: {seg.text}"

    def obs_speaker_line(seg: TranscriptSegment) -> str:
        label = format_transcript_speaker_label(seg.speaker, disp)
        return f"- [{seg.started_at.isoformat()}] **{label}**: {seg.text}"

    def app_shot_line(h: ScreenshotHit) -> str:
        rel = app_link_by_source.get(h.source_path, Path(h.source_path.name).as_posix())
        return markdown_image_line(
            alt=f"screenshot {h.captured_utc.isoformat(timespec='seconds')}",
            relative_link=rel,
        )

    def obs_shot_line(h: ScreenshotHit) -> str:
        rel = obs_link_by_source[h.source_path]
        return markdown_image_line(
            alt=f"screenshot {h.captured_utc.isoformat(timespec='seconds')}",
            relative_link=rel,
        )

    app_transcript_lines: list[str] | None = None
    obs_transcript_lines: list[str] | None = None
    if hits:
        app_transcript_lines = merge_transcript_lines_with_screenshots(
            segments,
            app_speaker_line,
            app_shot_line,
            session=session,
            shots=hits,
        )
        if obs_meeting_path is not None:
            obs_transcript_lines = merge_transcript_lines_with_screenshots(
                segments,
                obs_speaker_line,
                obs_shot_line,
                session=session,
                shots=hits,
            )

    app_path = app_exports_dir / export_filename_for_session(session)
    app_content = build_session_export_markdown(
        session=session,
        segments=segments,
        summary=summary,
        speaker_display=speaker_display,
        transcript_lines=app_transcript_lines,
    )

    obs_content: str | None = None
    if obs_meeting_path is not None:
        assert note_renderer is not None
        obs_content = note_renderer.render(
            session=session,
            segments=segments,
            summary=summary,
            speaker_display=speaker_display,
            transcript_lines=obs_transcript_lines,
        )

    return DualExportPrepared(
        app_path=app_path,
        app_content=app_content,
        obs_path=obs_meeting_path,
        obs_content=obs_content,
    )


def write_dual_export(
    *,
    app_base_dir: Path,
    session: MeetingSession,
    segments: list[TranscriptSegment],
    summary: Summary | None,
    speaker_display: dict[str, str] | None,
    note_renderer: MeetingNoteRenderer | None,
    screenshots_source_dir: Path | None = None,
    obsidian_screenshots_dir: Path | None = None,
    confirm_overwrite: ExportOverwriteConfirm | None = None,
) -> DualExportResult:
    """Plain markdown under app data dir; optional second file in the vault Meetings dir."""
    prepared = prepare_dual_export(
        app_base_dir=app_base_dir,
        session=session,
        segments=segments,
        summary=summary,
        speaker_display=speaker_display,
        note_renderer=note_renderer,
        screenshots_source_dir=screenshots_source_dir,
        obsidian_screenshots_dir=obsidian_screenshots_dir,
    )
    skipped: list[Path] = []

    app_written, app_decision = _write_export_content(
        prepared.app_path,
        prepared.app_content,
        confirm_overwrite=confirm_overwrite,
    )
    if app_decision == ExportWriteDecision.skip_identical:
        skipped.append(prepared.app_path)

    obs_path = prepared.obs_path
    obs_written = False
    if obs_path is not None and prepared.obs_content is not None:
        obs_path.parent.mkdir(parents=True, exist_ok=True)
        obs_written, obs_decision = _write_export_content(
            obs_path,
            prepared.obs_content,
            confirm_overwrite=confirm_overwrite,
        )
        if obs_decision == ExportWriteDecision.skip_identical:
            skipped.append(obs_path)

    return DualExportResult(
        app_path=prepared.app_path,
        obs_path=obs_path,
        app_written=app_written,
        obs_written=obs_written,
        skipped_identical=tuple(skipped),
    )
