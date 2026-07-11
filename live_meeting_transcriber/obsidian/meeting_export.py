from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

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
from live_meeting_transcriber.domain.meeting_naming import slug_title
from live_meeting_transcriber.domain.models import MeetingSession, Summary, TranscriptSegment
from live_meeting_transcriber.domain.speaker_display import format_transcript_speaker_label
from live_meeting_transcriber.obsidian.vault_patterns import (
    is_placeholder_meeting_title,
    safe_obsidian_filename_title,
)


class ExportCancelledError(Exception):
    """Raised when the user declines to overwrite an existing export file."""

    def __init__(self, path: Path) -> None:
        self.path = path
        super().__init__(f"Export cancelled for {path}")


@dataclass(frozen=True)
class DualExportResult:
    app_path: Path
    obs_path: Path | None
    app_written: bool
    obs_written: bool
    skipped_identical: tuple[Path, ...] = ()


def _yaml_attendees_list(names: list[str]) -> str:
    if not names:
        return "[]"
    escaped = [n.replace('"', '\\"') for n in names]
    inner = ", ".join(f'"{x}"' for x in escaped)
    return f"[{inner}]"


def _yaml_tags_list(tags: list[str]) -> str:
    if not tags:
        return "[meeting]"
    escaped = [t.replace('"', '\\"') for t in tags]
    inner = ", ".join(f'"{x}"' for x in escaped)
    return f"[{inner}]"


def _replace_frontmatter_scalar(content: str, key: str, value: str) -> str:
    quoted = value.replace('"', '\\"')
    replacement = f'{key}: "{quoted}"' if value else f'{key}: ""'
    pattern = rf"^{re.escape(key)}:\s*.*$"
    if re.search(pattern, content, flags=re.MULTILINE):
        return re.sub(pattern, replacement, content, count=1, flags=re.MULTILINE)
    return content


def _replace_frontmatter_list(content: str, key: str, values: list[str]) -> str:
    if key == "attendees":
        rendered = _yaml_attendees_list(values)
    elif key == "tags":
        rendered = _yaml_tags_list(values)
    else:
        rendered = _yaml_attendees_list(values)
    pattern = rf"^{re.escape(key)}:\s*.*$"
    if re.search(pattern, content, flags=re.MULTILINE):
        return re.sub(pattern, f"{key}: {rendered}", content, count=1, flags=re.MULTILINE)
    return content


def _replace_under_heading(content: str, heading: str, new_body: str) -> str:
    """Replace everything under ``## {heading}`` until the next ``##`` at line start."""
    marker = f"## {heading}\n"
    idx = content.find(marker)
    if idx == -1:
        return content
    start = idx + len(marker)
    rest = content[start:]
    next_h = re.search(r"\n## ", rest)
    end_rel = next_h.start() if next_h else len(rest)
    return content[:start] + new_body.strip() + "\n" + rest[end_rel:]


def _effective_attendees(session: MeetingSession, summary: Summary | None) -> list[str]:
    attendees = list(session.attendees)
    meta = summary.meeting_metadata if summary else None
    if meta is not None:
        for name in meta.confident_participants():
            if name not in attendees:
                attendees.append(name)
    return attendees


def _apply_summary_metadata_to_template(body: str, summary: Summary | None) -> str:
    meta = summary.meeting_metadata if summary else None
    if meta is None:
        return body

    topic = meta.confident_str("topic")
    if topic:
        body = _replace_frontmatter_scalar(body, "topic", topic)

    tags = meta.confident_tags()
    if tags:
        body = _replace_frontmatter_list(body, "tags", tags)

    series = meta.confident_str("series")
    if series:
        body = _replace_frontmatter_scalar(body, "series", series)

    location = meta.confident_str("location")
    if location:
        body = _replace_frontmatter_scalar(body, "location", location)

    related = meta.confident_str("related")
    if related:
        body = _replace_frontmatter_scalar(body, "related", related)

    return body


def render_meeting_note(
    *,
    template_text: str,
    session: MeetingSession,
    segments: list[TranscriptSegment],
    summary: Summary | None,
    speaker_display: dict[str, str] | None = None,
    transcript_lines: list[str] | None = None,
) -> str:
    """Fill ``Templates/Meeting.md``-style placeholders and inject notes / summary / transcript."""
    disp = speaker_display or {}
    d = session.started_at.date().isoformat()
    t = session.started_at.strftime("%H:%M")
    attendees = _effective_attendees(session, summary)
    body = template_text.replace("{{date}}", d)
    body = body.replace("{{time}}", t)
    body = body.replace("{{title}}", session.title)
    body = re.sub(
        r"^attendees:\s*\[\s*\]\s*$",
        f"attendees: {_yaml_attendees_list(attendees)}",
        body,
        flags=re.MULTILINE,
    )
    if attendees:
        body = re.sub(
            r"^(- \*\*Attendees\*\*:)\s*$",
            rf"\1 {', '.join(attendees)}",
            body,
            flags=re.MULTILINE,
        )

    body = _apply_summary_metadata_to_template(body, summary)

    notes_parts: list[str] = []
    if session.notes.strip():
        notes_parts.append(session.notes.strip())
    if summary and summary.summary_markdown.strip():
        notes_parts.append(summary.summary_markdown.strip())
    notes_block = "\n\n".join(notes_parts) if notes_parts else "_—_"

    decisions_block = (
        "\n".join(f"- {x.text}" for x in summary.decisions)
        if summary and summary.decisions
        else "- _—_"
    )
    actions_block = (
        "\n".join(f"- [ ] {x.text}" for x in summary.action_items)
        if summary and summary.action_items
        else "- [ ] _—_"
    )

    if transcript_lines is not None:
        transcript_block = "\n".join(transcript_lines) if transcript_lines else "- _—_"
    else:
        tlines: list[str] = []
        for seg in segments:
            label = format_transcript_speaker_label(seg.speaker, disp)
            tlines.append(f"- [{seg.started_at.isoformat()}] **{label}**: {seg.text}")
        transcript_block = "\n".join(tlines) if tlines else "- _—_"

    body = _replace_under_heading(body, "Notes", notes_block)
    body = _replace_under_heading(body, "Decisions", decisions_block)
    body = _replace_under_heading(body, "Action items", actions_block)
    body = _replace_under_heading(body, "Meeting Transcript", transcript_block)

    return body.rstrip() + "\n"


def meeting_export_filename(session: MeetingSession) -> str:
    """Stable filename: ``YYYY-MM-DD Title.md`` when title is meaningful, else slug form."""
    day = session.started_at.date().isoformat()
    if not is_placeholder_meeting_title(session.title):
        safe = safe_obsidian_filename_title(session.title)
        return f"{day} {safe}.md"
    slug = slug_title(session.title, max_len=56)
    return f"{day}_{slug}.md"


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


def write_obsidian_meeting(
    *,
    meetings_dir: Path,
    template_path: Path,
    session: MeetingSession,
    segments: list[TranscriptSegment],
    summary: Summary | None,
    speaker_display: dict[str, str] | None = None,
    transcript_lines: list[str] | None = None,
    confirm_overwrite: ExportOverwriteConfirm | None = None,
) -> tuple[Path, bool, ExportWriteDecision]:
    meetings_dir.mkdir(parents=True, exist_ok=True)
    template_text = template_path.read_text(encoding="utf-8")
    content = render_meeting_note(
        template_text=template_text,
        session=session,
        segments=segments,
        summary=summary,
        speaker_display=speaker_display,
        transcript_lines=transcript_lines,
    )
    path = meetings_dir / meeting_export_filename(session)
    written, decision = _write_export_content(path, content, confirm_overwrite=confirm_overwrite)
    return path, written, decision


@dataclass(frozen=True)
class DualExportPrepared:
    app_path: Path
    app_content: str
    obs_path: Path | None
    obs_content: str | None


def prepare_dual_export(
    *,
    app_base_dir: Path,
    session: MeetingSession,
    segments: list[TranscriptSegment],
    summary: Summary | None,
    speaker_display: dict[str, str] | None,
    obsidian_meetings_dir: Path | None,
    obsidian_meeting_template: Path | None,
    screenshots_source_dir: Path | None = None,
    obsidian_screenshots_dir: Path | None = None,
) -> DualExportPrepared:
    """Build export paths and markdown without writing files."""
    from live_meeting_transcriber.application.export_markdown import (
        build_session_export_markdown,
        export_filename_for_session,
    )

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
    if (
        obsidian_meetings_dir is not None
        and obsidian_meeting_template is not None
        and obsidian_meeting_template.is_file()
    ):
        obs_meeting_path = obsidian_meetings_dir / meeting_export_filename(session)

    obs_shot_dir = obsidian_screenshots_dir
    if hits and obs_meeting_path is not None:
        if obs_shot_dir is None:
            obs_shot_dir = (obs_meeting_path.parent.parent / "Images" / "Screenshots").resolve()
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
        template_text = obsidian_meeting_template.read_text(encoding="utf-8")  # type: ignore[union-attr]
        obs_content = render_meeting_note(
            template_text=template_text,
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
    obsidian_meetings_dir: Path | None,
    obsidian_meeting_template: Path | None,
    screenshots_source_dir: Path | None = None,
    obsidian_screenshots_dir: Path | None = None,
    confirm_overwrite: ExportOverwriteConfirm | None = None,
) -> DualExportResult:
    """Plain markdown under app data dir; optional second file in Obsidian Meetings."""
    prepared = prepare_dual_export(
        app_base_dir=app_base_dir,
        session=session,
        segments=segments,
        summary=summary,
        speaker_display=speaker_display,
        obsidian_meetings_dir=obsidian_meetings_dir,
        obsidian_meeting_template=obsidian_meeting_template,
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
        obsidian_meetings_dir.mkdir(parents=True, exist_ok=True)  # type: ignore[union-attr]
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
