"""Meetings-tab action flows (A5, ARCH-10).

The write/command side of the ``MeetingBrowser`` widget: the bodies of its toolbar and
key-binding actions (save, summarize, delete, video import, slide preview, speaker ID,
continue recording, …) plus their modal-callback continuations. Pure moves out of
``meeting_browser.py`` — each flow takes the browser and operates on its widgets/state
exactly as the former methods did. The widget keeps thin ``action_*`` delegates so
BINDINGS, the toolbar catalog (``dispatch_toolbar_action``), and the ? overlay are
unchanged.
"""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING
from uuid import UUID

from textual.widgets import Button, DataTable, Static, TextArea

from live_meeting_transcriber.application.cleanup_service import purge_session_artifacts
from live_meeting_transcriber.application.session_media import (
    collect_session_media,
    format_session_media_inventory,
)
from live_meeting_transcriber.application.session_service import SessionService
from live_meeting_transcriber.application.video_import_service import VideoImportProgress
from live_meeting_transcriber.ui.state import actions as act
from live_meeting_transcriber.ui.state.model import RecordingStatus
from live_meeting_transcriber.ui.tui import meeting_detail
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
    session_has_slide_source,
)
from live_meeting_transcriber.ui.tui.meeting_toolbar import overflow_toolbar_actions
from live_meeting_transcriber.ui.tui.slide_preview_screen import SlidePreviewScreen
from live_meeting_transcriber.ui.tui.tab_complete_input import TabCompletableInput
from live_meeting_transcriber.ui.tui.video_import_modal import (
    VideoImportForm,
    VideoImportModal,
    format_video_import_error,
    run_video_import,
)
from live_meeting_transcriber.utils.time import utc_now

if TYPE_CHECKING:
    from live_meeting_transcriber.ui.tui.meeting_browser import MeetingBrowser

# One start notice for every Speaker ID trigger path (F10): it must say that the
# action retranscribes the whole meeting — the transcript is replaced, not merely
# annotated with speaker labels.
SPEAKER_ID_STARTED_NOTICE = (
    "Speaker ID / Retranscribe queued (WhisperX) — retranscribes the whole meeting "
    "and replaces its transcript. Progress: status deck + jobs panel."
)


async def import_video(browser: MeetingBrowser) -> None:
    await browser.app.push_screen(
        VideoImportModal(),
        callback=functools.partial(_after_video_import_modal, browser),
    )


def _after_video_import_modal(browser: MeetingBrowser, form: VideoImportForm | None) -> None:
    if form is None:
        return
    browser.run_worker(_execute_video_import(browser, form), exclusive=True, group="video-import")


async def _execute_video_import(browser: MeetingBrowser, form: VideoImportForm) -> None:
    status = browser.query_one("#meeting-detail-status", Static)
    status.update("[dim]Importing video…[/]")
    slide_btn = browser.query_one("#meeting-btn-slide-preview", Button)
    slide_btn.disabled = True
    browser.app.notify(
        f"Importing video from {form.source[:64]}{'…' if len(form.source) > 64 else ''}…",
        severity="information",
    )

    def _on_progress(p: VideoImportProgress) -> None:
        if p.phase == "slides":
            status.update("[dim]Importing — detecting slides…[/]")
            browser.app.notify("Detecting slides…", severity="information", timeout=3)
            return
        pct = int(100 * p.chunk_index / p.chunk_total) if p.chunk_total else 0
        status.update(
            f"[dim]Importing — transcribing chunk {p.chunk_index}/{p.chunk_total} ({pct}%)…[/]"
        )
        browser.app.notify(
            f"Transcribing chunk {p.chunk_index}/{p.chunk_total} ({pct}%) — "
            f"{p.segments_so_far} segment(s) so far",
            severity="information",
            timeout=4,
        )

    try:
        result = await run_video_import(
            browser.container,
            source=form.source,
            title=form.title,
            on_progress=_on_progress,
        )
    except Exception as e:
        browser.app.notify(format_video_import_error(e), severity="error", timeout=8)
        return

    await browser.store.dispatch_with_effects(act.SessionsRefreshRequested(at=utc_now()))
    browser._selected_session_id = result.session_id
    browser.refresh_session_list(preserve_selection=True)
    table = browser.query_one("#meeting-sessions-table", DataTable)
    for i, s in enumerate(browser.container.sessions.list()):
        if s.id == result.session_id:
            table.move_cursor(row=i)
            break
    await meeting_detail.load_detail(browser, result.session_id)
    session = browser.container.sessions.get(result.session_id)
    title = session.title if session is not None else "video"
    msg = (
        f"Imported “{title}” — {result.segment_count} segment(s). "
        "Press [bold]p[/] for slide preview."
    )
    if result.transcription is not None:
        warning = result.transcription.status_message()
        if warning is not None and result.transcription.segments > 0:
            browser.app.notify(warning, severity="warning", timeout=10)
    browser.app.notify(msg, timeout=6)


async def save_meeting(browser: MeetingBrowser) -> None:
    if browser._selected_session_id is None:
        browser.app.notify("Select a meeting first.", severity="warning")
        return
    sid = browser._selected_session_id
    title = browser.query_one("#meeting-title", TabCompletableInput).value.strip()
    notes = browser.query_one("#meeting-notes", TextArea).text
    raw_att = browser.query_one("#meeting-attendees", TabCompletableInput).value
    parts = [p.strip() for p in raw_att.replace("\n", ",").split(",")]
    attendees = [p for p in parts if p]

    if not title:
        browser.app.notify("Title required.", severity="error")
        return

    updated = browser.container.sessions.update_details(
        sid, title=title, notes=notes, attendees=attendees
    )
    if updated is None:
        browser.app.notify("Save failed.", severity="error")
        return

    mapping: dict[str, str] = {}
    for sk in browser._speaker_keys:
        inp = browser.query_one(f"#spk-{sk}", TabCompletableInput)
        mapping[sk] = inp.value.strip()
    browser.container.session_speakers.replace_map(sid, mapping)

    for name in attendees:
        browser.container.people.touch(name)
    for v in mapping.values():
        if v:
            browser.container.people.touch(v)

    await browser.store.dispatch_with_effects(act.SessionsRefreshRequested(at=utc_now()))
    browser.app.notify("Meeting saved (title, notes, attendees, speakers).")
    browser.refresh_session_list(preserve_selection=True)


async def finalize_selected_speakers(browser: MeetingBrowser) -> None:
    if browser._selected_session_id is None:
        browser.app.notify("Select a meeting first.", severity="warning")
        return
    sid = browser._selected_session_id
    browser.app.notify(SPEAKER_ID_STARTED_NOTICE, severity="information")
    await browser.store.dispatch_with_effects(
        act.FinalizeSessionRequested(session_id=sid, at=utc_now())
    )


async def summarize_meeting(browser: MeetingBrowser) -> None:
    if browser._selected_session_id is None:
        browser.app.notify("Select a meeting first.", severity="warning")
        return
    sid = browser._selected_session_id
    await browser.app.push_screen(
        SummaryContextModal(),
        callback=functools.partial(_after_summary_context_modal, browser, sid),
    )


def _after_summary_context_modal(browser: MeetingBrowser, sid: UUID, context: str | None) -> None:
    if context is None:
        return
    user_ctx = context or None
    browser.run_worker(_run_summarize(browser, sid, user_ctx), exclusive=True)


async def _run_summarize(browser: MeetingBrowser, sid: UUID, user_context: str | None) -> None:
    browser.app.notify("Summarizing… (OpenAI)")
    svc = SessionService(
        sessions=browser.container.sessions,
        transcripts=browser.container.transcripts,
        summaries=browser.container.summaries,
        summarizer=browser.container.summarizer,
        session_speakers=browser.container.session_speakers,
    )
    try:
        await svc.summarize_session(session_id=sid, user_context=user_context)
    except Exception as e:
        browser.app.notify(f"Summarize failed: {e}", severity="error")
        return
    browser.app.notify("Summary saved.")
    await browser.store.dispatch_with_effects(act.SessionsRefreshRequested(at=utc_now()))
    await meeting_detail.load_detail(browser, sid)


async def show_session_media(browser: MeetingBrowser) -> None:
    if browser._selected_session_id is None:
        browser.app.notify("Select a meeting first.", severity="warning")
        return
    data_dir = browser.container.settings.ensure_data_dir()
    inventory = collect_session_media(data_dir, browser._selected_session_id)
    body = format_session_media_inventory(inventory)
    await browser.app.push_screen(SessionMediaModal(body=body))


async def slide_preview(browser: MeetingBrowser) -> None:
    if browser._selected_session_id is None:
        browser.app.notify("Select a meeting first.", severity="warning")
        return
    data_dir = browser.container.settings.ensure_data_dir()
    if not session_has_slide_source(data_dir, browser._selected_session_id):
        browser.app.notify(
            "Slide preview needs a session with source video on disk "
            "(import with ctrl+v or transcribe-video).",
            severity="warning",
        )
        return
    await browser.app.push_screen(
        SlidePreviewScreen(
            container=browser.container,
            session_id=browser._selected_session_id,
        ),
        callback=functools.partial(_after_slide_preview, browser),
    )


def _after_slide_preview(browser: MeetingBrowser, _result: None) -> None:
    if browser._selected_session_id is None:
        return
    sid = browser._selected_session_id
    data_dir = browser.container.settings.ensure_data_dir()
    saved = count_saved_slides(data_dir, sid)
    preview_count = count_preview_candidates(data_dir, sid)

    async def _reload() -> None:
        await meeting_detail.load_detail(browser, sid)
        if preview_count and saved == 0:
            browser.app.notify(
                "Preview complete — use [bold]Apply all candidates[/] or mark rows with "
                "[bold]y[/] then [bold]Apply kept slides[/] in slide preview.",
                severity="information",
                timeout=8,
            )
        elif saved:
            browser.app.notify(
                f"{saved} slide(s) saved — ready to export with [bold]w[/].",
                severity="information",
                timeout=6,
            )

    browser.run_worker(_reload(), exclusive=True)


async def refresh_list(browser: MeetingBrowser) -> None:
    browser.refresh_session_list(preserve_selection=True)
    if browser._selected_session_id is not None:
        await meeting_detail.load_detail(browser, browser._selected_session_id)
    browser.app.notify("Refreshed.")


async def export_meeting(browser: MeetingBrowser) -> None:
    if browser._selected_session_id is None:
        browser.app.notify("Select a meeting first.", severity="warning")
        return
    await browser.store.dispatch_with_effects(
        act.ExportMarkdownRequested(at=utc_now(), session_id=browser._selected_session_id)
    )


async def continue_recording(browser: MeetingBrowser) -> None:
    if browser._selected_session_id is None:
        browser.app.notify("Select a meeting in the list first.", severity="warning")
        return
    st = browser.store.get_state()
    if st.recording_status in (
        RecordingStatus.starting,
        RecordingStatus.recording,
        RecordingStatus.stopping,
    ):
        browser.app.notify(
            "Stop the current recording before continuing another meeting.", severity="warning"
        )
        return
    session = browser.container.sessions.get(browser._selected_session_id)
    if session is None:
        browser.app.notify("Meeting not found in the database.", severity="error")
        return
    await browser.store.dispatch_with_effects(
        act.RecordingStartRequested(
            title=session.title,
            audio_source=st.audio_source,
            at=utc_now(),
            resume_session_id=session.id,
        )
    )
    browser.app.notify(
        f"Recording into: {session.title}. Switch to the Live tab for the transcript."
    )
    focus = getattr(browser.app, "action_focus_live_tab", None)
    if callable(focus):
        focus()


async def show_more_menu(browser: MeetingBrowser) -> None:
    await browser.app.push_screen(
        MeetingActionsMenu(overflow_toolbar_actions()),
        callback=functools.partial(_after_more_menu, browser),
    )


def _after_more_menu(browser: MeetingBrowser, action_name: str | None) -> None:
    if action_name is None:
        return
    browser.run_worker(browser.dispatch_toolbar_action(action_name))


async def delete_meeting(browser: MeetingBrowser) -> None:
    if browser._selected_session_id is None:
        browser.app.notify("Select a meeting first.", severity="warning")
        return
    sid = browser._selected_session_id
    st = browser.store.get_state()
    if st.current_session_id == sid and st.recording_status in (
        RecordingStatus.starting,
        RecordingStatus.recording,
        RecordingStatus.stopping,
    ):
        browser.app.notify(
            "Cannot delete the meeting while recording is in progress.", severity="error"
        )
        return
    title = (
        browser.query_one("#meeting-title", TabCompletableInput).value.strip() or str(sid)[:8] + "…"
    )
    await browser.app.push_screen(
        ConfirmDeleteMeetingModal(title=title, session_id=sid),
        callback=functools.partial(_after_delete_meeting_confirm, browser, sid),
    )


def _after_delete_meeting_confirm(
    browser: MeetingBrowser, sid: UUID, confirmed: bool | None
) -> None:
    if not confirmed:
        return
    browser.run_worker(_complete_delete_meeting(browser, sid), exclusive=True)


async def _complete_delete_meeting(browser: MeetingBrowser, sid: UUID) -> None:
    catalog_before = browser.container.sessions.list()
    try:
        del_idx = next(i for i, s in enumerate(catalog_before) if s.id == sid)
    except StopIteration:
        del_idx = 0
    removed = browser.container.sessions.delete(sid)
    if removed:
        purge_session_artifacts(
            browser.container.settings.ensure_data_dir(),
            sid,
            dry_run=False,
        )
        browser.app.notify("Meeting deleted.")
    else:
        browser.app.notify("Meeting was already removed.", severity="warning")

    remaining = browser.container.sessions.list()
    if remaining:
        pick = min(del_idx, len(remaining) - 1)
        browser._selected_session_id = remaining[pick].id
    else:
        browser._selected_session_id = None

    await browser.store.dispatch_with_effects(act.SessionsRefreshRequested(at=utc_now()))
    browser.refresh_session_list(preserve_selection=True)

    if browser._selected_session_id is not None:
        table = browser.query_one("#meeting-sessions-table", DataTable)
        for i, s in enumerate(browser.container.sessions.list()):
            if s.id == browser._selected_session_id:
                table.move_cursor(row=i)
                break
        await meeting_detail.load_detail(browser, browser._selected_session_id)
    else:
        await meeting_detail.clear_detail(browser)


async def edit_segment(browser: MeetingBrowser) -> None:
    if browser._selected_session_id is None or not browser._segments:
        browser.app.notify("Select a meeting with transcript lines.", severity="warning")
        return
    transcript = browser.query_one("#meeting-transcript", TextArea)
    row = transcript.cursor_location[0]
    if row < 0 or row >= len(browser._transcript_row_ids):
        browser.app.notify("Place the cursor on a transcript line first.", severity="warning")
        return
    seg_id = UUID(browser._transcript_row_ids[row])
    seg = next((s for s in browser._segments if s.id == seg_id), None)
    if seg is None:
        return
    await browser.app.push_screen(
        EditSegmentModal(container=browser.container, segment=seg),
        callback=functools.partial(_after_edit_segment_modal, browser),
    )


def _after_edit_segment_modal(browser: MeetingBrowser, result: bool | None) -> None:
    if not result or browser._selected_session_id is None:
        return
    sid = browser._selected_session_id

    async def _reload() -> None:
        await meeting_detail.load_detail(browser, sid)

    browser.run_worker(_reload(), exclusive=True)
