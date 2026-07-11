"""U24 — broader Live sidebar with a labeled meeting-details panel.

Widens the Live sidebar and gives the meeting fields explicit labels, a titled panel, a live
attendee summary, and a roomier Notes box (operator-directed; supersedes U8's max-transcript
width tradeoff). The auto-save behavior and widget IDs from U23 are unchanged.
"""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from live_meeting_transcriber.domain.models import MeetingSession
from live_meeting_transcriber.ui.tui.app import TranscriberApp
from live_meeting_transcriber.ui.tui.tab_complete_input import TabCompletableInput
from textual.widgets import RichLog, Static

from tests.unit.conftest import make_tui_app


def _app_with_session(sid: object, existing: MeetingSession) -> TranscriberApp:
    container = MagicMock()
    container.sessions.list.return_value = []
    container.sessions.get.return_value = existing
    container.devices.list_sources.return_value = [object()]
    return make_tui_app(
        container,
        state_updates={"current_session_id": sid, "session_title": existing.title},
    )


async def test_sidebar_is_broader_transcript_still_workable() -> None:
    # Operator-directed: broaden the sidebar (>= 44) for the meeting fields while the
    # transcript keeps a usable width (> 60). Supersedes U8's transcript-> 80 tradeoff.
    app = _app_with_session(uuid4(), MeetingSession(id=uuid4(), title="x"))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        sidebar = app.query_one("#sidebar")
        transcript = app.query_one("#transcript", RichLog)
        assert sidebar.size.width >= 44
        assert transcript.size.width > 60


async def test_meeting_fields_have_labels_and_titled_panel() -> None:
    sid = uuid4()
    app = _app_with_session(sid, MeetingSession(id=sid, title="Weekly sync"))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        panel = app.query_one("#live-details")
        # Titled panel makes the auto-save behavior discoverable.
        assert "saves automatically" in str(panel.border_title).lower()
        labels = [str(w.render()) for w in app.query(".field-label")]
        joined = " ".join(labels)
        assert "Title" in joined
        assert "Attendees" in joined
        assert "Notes" in joined


async def test_attendees_summary_reflects_the_field() -> None:
    sid = uuid4()
    app = _app_with_session(sid, MeetingSession(id=sid, title="Weekly sync"))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        summary = app.query_one("#live-attendees-summary", Static)
        # Empty → a dim "no attendees yet" hint, not a blank line.
        assert "no attendees" in str(summary.render()).lower()

        att = app.query_one("#live-attendees", TabCompletableInput)
        att.value = "Alice, Bob"
        await pilot.pause()
        rendered = str(summary.render())
        assert "Alice" in rendered
        assert "Bob" in rendered
