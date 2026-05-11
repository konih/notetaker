from __future__ import annotations

import os
import re
from pathlib import Path

from live_meeting_transcriber.application.screenshot_export import (
    ScreenshotHit,
    copy_screenshot_for_export,
    list_session_screenshots,
    markdown_image_line,
    merge_transcript_lines_with_screenshots,
)
from live_meeting_transcriber.domain.models import MeetingSession, Summary, TranscriptSegment
from live_meeting_transcriber.domain.speaker_display import format_transcript_speaker_label


def _yaml_attendees_list(names: list[str]) -> str:
    if not names:
        return "[]"
    escaped = [n.replace('"', '\\"') for n in names]
    inner = ", ".join(f'"{x}"' for x in escaped)
    return f"[{inner}]"


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
    body = template_text.replace("{{date}}", d)
    body = body.replace("{{time}}", t)
    body = body.replace("{{title}}", session.title)
    body = re.sub(
        r"^attendees:\s*\[\s*\]\s*$",
        f"attendees: {_yaml_attendees_list(session.attendees)}",
        body,
        flags=re.MULTILINE,
    )
    if session.attendees:
        body = re.sub(
            r"^(- \*\*Attendees\*\*:)\s*$",
            rf"\1 {', '.join(session.attendees)}",
            body,
            flags=re.MULTILINE,
        )

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
    """Stable filename: ``YYYY-MM-DD_slug.md``."""
    from live_meeting_transcriber.application.export_markdown import _slug_title

    day = session.started_at.date().isoformat()
    slug = _slug_title(session.title, max_len=56)
    return f"{day}_{slug}.md"


def write_obsidian_meeting(
    *,
    meetings_dir: Path,
    template_path: Path,
    session: MeetingSession,
    segments: list[TranscriptSegment],
    summary: Summary | None,
    speaker_display: dict[str, str] | None = None,
    transcript_lines: list[str] | None = None,
) -> Path:
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
    path.write_text(content, encoding="utf-8")
    return path


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
) -> tuple[Path, Path | None]:
    """Plain markdown under app data dir; optional second file in Obsidian Meetings."""
    from live_meeting_transcriber.application.export_markdown import write_session_export_markdown

    disp = speaker_display or {}
    hits = list_session_screenshots(screenshots_source_dir, session, segments)
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

    app_path = write_session_export_markdown(
        base_dir=app_base_dir,
        session=session,
        segments=segments,
        summary=summary,
        speaker_display=speaker_display,
        transcript_lines=app_transcript_lines,
    )
    obs_path: Path | None = None
    if obs_meeting_path is not None:
        obs_path = write_obsidian_meeting(
            meetings_dir=obsidian_meetings_dir,  # type: ignore[arg-type]
            template_path=obsidian_meeting_template,  # type: ignore[arg-type]
            session=session,
            segments=segments,
            summary=summary,
            speaker_display=speaker_display,
            transcript_lines=obs_transcript_lines,
        )
    return app_path, obs_path
