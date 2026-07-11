"""Meetings-tab queries and detail-pane loading (A5, ARCH-10).

The read side of the ``MeetingBrowser`` widget: refreshing the session list from the
container, and loading/clearing the detail pane widgets for a selected meeting. Pure
moves out of ``meeting_browser.py`` — each function takes the browser and operates on
its widgets/state exactly as the former methods did. The widget keeps thin delegating
methods (``refresh_session_list``, ``_load_detail``, ``_clear_detail``) so external
callers and Textual workers are unchanged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from rich.text import Text
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Static, TextArea

from live_meeting_transcriber.application.session_search import apply_session_query
from live_meeting_transcriber.domain.models import Summary
from live_meeting_transcriber.ui.state import actions as act
from live_meeting_transcriber.ui.tui.empty_states import MEETINGS_EMPTY_HINT
from live_meeting_transcriber.ui.tui.footer_bindings import footer_key
from live_meeting_transcriber.ui.tui.meeting_session_helpers import (
    count_preview_candidates,
    count_saved_slides,
    format_slide_detail_note,
    list_preview_candidate_timestamps,
    meeting_row_cells,
    session_has_slide_source,
    session_is_video_import,
)
from live_meeting_transcriber.ui.tui.rendering import speaker_color
from live_meeting_transcriber.ui.tui.tab_complete_input import TabCompletableInput
from live_meeting_transcriber.ui.tui.transcript_display import format_meeting_transcript_text
from live_meeting_transcriber.utils.time import utc_now

if TYPE_CHECKING:
    from live_meeting_transcriber.ui.tui.meeting_browser import MeetingBrowser

# Canonical Summarize key (UX-OQ-3): sourced from the global footer catalog so every
# inline hint on this tab renders the same key as the footer and the ? overlay (U12).
SUMMARIZE_KEY = footer_key("summarize")


def format_summary_for_editor(summary: Summary | None) -> str:
    if summary is None:
        return f"— No summary yet. Press {SUMMARIZE_KEY} to generate. —"
    parts: list[str] = [summary.summary_markdown.strip()]
    if summary.decisions:
        parts.append("## Decisions\n" + "\n".join(f"- {d.text}" for d in summary.decisions))
    if summary.action_items:
        parts.append(
            "## Action items\n" + "\n".join(f"- [ ] {ai.text}" for ai in summary.action_items)
        )
    return "\n\n".join(parts)


def refresh_session_list(browser: MeetingBrowser, *, preserve_selection: bool = False) -> None:
    table = browser.query_one("#meeting-sessions-table", DataTable)
    selected = (
        str(browser._selected_session_id)
        if preserve_selection and browser._selected_session_id
        else None
    )
    data_dir = browser.container.settings.ensure_data_dir()
    active_session_id = browser.store.get_state().current_session_id
    now = utc_now()
    sessions = apply_session_query(browser.container.sessions.list(), browser._filter_query)
    table.clear()
    for s in sessions:
        is_video = session_is_video_import(data_dir, s.id)
        glyph, style, title, started = meeting_row_cells(
            s, is_video=is_video, active_session_id=active_session_id, now=now
        )
        table.add_row(
            Text(glyph, style=style),
            title,
            Text(started, style="dim"),
            key=str(s.id),
        )
    visible_ids = [str(s.id) for s in sessions]
    if selected and selected in visible_ids:
        table.move_cursor(row=visible_ids.index(selected))
    elif selected:
        # The selected meeting was filtered out — keep list and detail in sync
        # (U17): fall to the first visible row, or clear the detail pane.
        browser._selected_session_id = None
        if table.row_count > 0:
            table.move_cursor(row=0)
        else:

            async def _clear_then_hint() -> None:
                await clear_detail(browser)
                update_empty_status(browser)

            browser.run_worker(_clear_then_hint(), exclusive=True)
    update_empty_status(browser)


def update_empty_status(browser: MeetingBrowser) -> None:
    """Empty-table guidance: first-run hint (U10) or an explicit no-match state (U17)."""
    if browser.query_one("#meeting-sessions-table", DataTable).row_count > 0:
        return
    status = browser.query_one("#meeting-detail-status", Static)
    if browser._filter_query.strip():
        status.update(
            f"No meetings match “{browser._filter_query.strip()}” — esc clears the filter."
        )
    else:
        status.update(MEETINGS_EMPTY_HINT)


async def load_detail(browser: MeetingBrowser, session_id: UUID) -> None:
    session = browser.container.sessions.get(session_id)
    if session is None:
        return
    status = browser.query_one("#meeting-detail-status", Static)
    data_dir = browser.container.settings.ensure_data_dir()
    is_video = session_is_video_import(data_dir, session_id)
    has_slide_source = session_has_slide_source(data_dir, session_id)
    saved_slides = count_saved_slides(data_dir, session_id)
    preview_count = count_preview_candidates(data_dir, session_id)
    preview_timestamps = list_preview_candidate_timestamps(data_dir, session_id)
    kind = "[cyan]Video import[/]" if is_video else "[green]Live recording[/]"
    slide_note = format_slide_detail_note(
        saved_slides=saved_slides,
        preview_count=preview_count,
        preview_timestamps=preview_timestamps,
        has_slide_source=has_slide_source,
    )
    status.update(f"Editing {kind} [bold]{session.title}[/bold] ({session_id}){slide_note}")

    continue_btn = browser.query_one("#meeting-btn-continue-record", Button)
    continue_btn.disabled = is_video
    slide_btn = browser.query_one("#meeting-btn-slide-preview", Button)
    slide_btn.disabled = not has_slide_source

    title_inp = browser.query_one("#meeting-title", TabCompletableInput)
    title_inp.disabled = False
    title_inp.value = session.title

    notes = browser.query_one("#meeting-notes", TextArea)
    notes.disabled = False
    notes.text = session.notes

    att = browser.query_one("#meeting-attendees", TabCompletableInput)
    att.disabled = False
    att.value = ", ".join(session.attendees)
    att.suggester = browser._comma_suggester

    summary = browser.container.summaries.get_by_session(session_id)
    sum_ta = browser.query_one("#meeting-summary", TextArea)
    sum_ta.disabled = False
    sum_ta.text = format_summary_for_editor(summary)
    sum_ta.disabled = True

    browser._segments = browser.container.transcripts.list_by_session(session_id)
    name_map = browser.container.session_speakers.get_map(session_id)
    browser._speaker_keys = sorted({s.speaker for s in browser._segments})

    spk_area = browser.query_one("#meeting-speaker-area", Vertical)
    await spk_area.remove_children()
    rows: list[Horizontal] = []
    for sk in browser._speaker_keys:
        chip = Text.assemble(
            ("▍", speaker_color(sk)), (f"{sk} ", f"bold {speaker_color(sk)}"), ("→", "dim")
        )
        rows.append(
            Horizontal(
                Static(chip, classes="spk-label"),
                TabCompletableInput(
                    value=name_map.get(sk, ""),
                    placeholder="Display name",
                    suggester=browser._prefix_suggester,
                    id=f"spk-{sk}",
                    classes="spk-inp",
                ),
                classes="spk-row",
            )
        )
    if rows:
        await spk_area.mount(*rows)

    transcript = browser.query_one("#meeting-transcript", TextArea)
    transcript.text = format_meeting_transcript_text(browser._segments, session, name_map)
    browser._transcript_row_ids = [str(s.id) for s in browser._segments]

    st = browser.store.get_state()
    if st.pending_meeting_detail_reload == session_id:
        browser.store.dispatch(act.DetailReloadAcknowledged(at=utc_now()))


async def clear_detail(browser: MeetingBrowser) -> None:
    browser._selected_session_id = None
    browser._segments = []
    browser._transcript_row_ids = []
    browser._speaker_keys = []
    browser.query_one("#meeting-detail-status", Static).update("No meeting selected.")
    browser.query_one("#meeting-title", TabCompletableInput).value = ""
    browser.query_one("#meeting-title", TabCompletableInput).disabled = True
    notes = browser.query_one("#meeting-notes", TextArea)
    notes.text = ""
    notes.disabled = True
    sum_ta = browser.query_one("#meeting-summary", TextArea)
    sum_ta.text = ""
    sum_ta.disabled = True
    att = browser.query_one("#meeting-attendees", TabCompletableInput)
    att.value = ""
    att.disabled = True
    spk_area = browser.query_one("#meeting-speaker-area", Vertical)
    await spk_area.remove_children()
    browser.query_one("#meeting-transcript", TextArea).text = ""
    continue_btn = browser.query_one("#meeting-btn-continue-record", Button)
    continue_btn.disabled = False
    slide_btn = browser.query_one("#meeting-btn-slide-preview", Button)
    slide_btn.disabled = True
