"""U23 — inline auto-saving meeting fields on the Live tab.

The Live sidebar carries always-visible Title / Attendees / Notes fields for the current
live meeting. Edits save automatically (no Save button, no modal) via the existing
``SessionDetailsCommitRequested`` path — on Enter, on blur, and flushed on stop.
"""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from live_meeting_transcriber.domain.models import MeetingSession
from live_meeting_transcriber.ui.state import actions as act
from live_meeting_transcriber.ui.tui.app import TranscriberApp
from live_meeting_transcriber.ui.tui.tab_complete_input import TabCompletableInput
from live_meeting_transcriber.utils.time import utc_now
from textual.widgets import TextArea

from tests.unit.conftest import make_tui_app


def _app_with_live_session(
    sid: object,
    existing: MeetingSession,
    *,
    with_session: bool = True,
) -> tuple[TranscriberApp, MagicMock]:
    container = MagicMock()
    container.sessions.list.return_value = []
    container.sessions.get.return_value = existing
    container.sessions.update_details.return_value = existing.model_copy(
        update={"title": "Weekly standup", "notes": "Agenda", "attendees": ["Alice", "Bob"]}
    )
    update: dict[str, object] = {}
    if with_session:
        update = {"current_session_id": sid, "session_title": existing.title}
    app = make_tui_app(container, state_updates=update)
    return app, container


async def test_fields_populate_from_current_session() -> None:
    # AC: starting/holding a live meeting shows the fields pre-filled from the session.
    sid = uuid4()
    existing = MeetingSession(id=sid, title="Meeting 2026-07-10", notes="Prep", attendees=["Carol"])
    app, _container = _app_with_live_session(sid, existing)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        title = app.query_one("#live-title", TabCompletableInput)
        attendees = app.query_one("#live-attendees", TabCompletableInput)
        notes = app.query_one("#live-notes", TextArea)
        assert title.value == "Meeting 2026-07-10"
        assert attendees.value == "Carol"
        assert notes.text == "Prep"
        assert not title.disabled


async def test_autosave_persists_and_refreshes_header() -> None:
    # AC: editing inline + saving calls update_details and the Live header refreshes — no button.
    sid = uuid4()
    existing = MeetingSession(id=sid, title="Meeting 2026-07-10")
    app, container = _app_with_live_session(sid, existing)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.query_one("#live-title", TabCompletableInput).value = "Weekly standup"
        app.query_one("#live-notes", TextArea).text = "Agenda"
        app.query_one("#live-attendees", TabCompletableInput).value = "Alice, Bob"
        await app._save_live_details()
        await pilot.pause()

    container.sessions.update_details.assert_called_once_with(
        sid, title="Weekly standup", notes="Agenda", attendees=["Alice", "Bob"]
    )
    assert app.store.get_state().session_title == "Weekly standup"


async def test_empty_title_skips_autosave_silently() -> None:
    # AC: a blank title on auto-save persists nothing and raises no error toast.
    sid = uuid4()
    existing = MeetingSession(id=sid, title="Meeting 2026-07-10")
    app, container = _app_with_live_session(sid, existing)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.query_one("#live-title", TabCompletableInput).value = "   "
        await app._save_live_details()
        await pilot.pause()

    container.sessions.update_details.assert_not_called()
    assert app.store.get_state().recent_errors == ()


async def test_unchanged_values_do_not_re_persist() -> None:
    # AC: repeated saves without a change are no-ops (no DB write per blur/tick).
    sid = uuid4()
    existing = MeetingSession(id=sid, title="Meeting 2026-07-10", notes="", attendees=[])
    app, container = _app_with_live_session(sid, existing)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await app._save_live_details()
        await app._save_live_details()
        await pilot.pause()

    container.sessions.update_details.assert_not_called()


async def test_inline_fields_do_not_steal_default_focus() -> None:
    # Regression guard: the inline inputs are the first sidebar children, but they must not
    # grab initial focus — otherwise single-key Live bindings (r/x/t/…) would be typed into
    # the title field instead of triggering their actions.
    sid = uuid4()
    existing = MeetingSession(id=sid, title="Meeting 2026-07-10")
    app, _container = _app_with_live_session(sid, existing)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        focused_id = getattr(app.focused, "id", None)
        assert focused_id not in ("live-title", "live-attendees", "live-notes")


async def test_submit_triggers_autosave() -> None:
    # AC: pressing Enter in the title field auto-saves (no Save button).
    sid = uuid4()
    existing = MeetingSession(id=sid, title="Meeting 2026-07-10")
    app, container = _app_with_live_session(sid, existing)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        title = app.query_one("#live-title", TabCompletableInput)
        title.focus()
        title.value = "Renamed"
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

    assert container.sessions.update_details.call_args.kwargs["title"] == "Renamed"


async def test_blur_triggers_autosave() -> None:
    # AC: moving focus off a field (blur) auto-saves — the only trigger for notes.
    sid = uuid4()
    existing = MeetingSession(id=sid, title="Meeting 2026-07-10")
    app, container = _app_with_live_session(sid, existing)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        notes = app.query_one("#live-notes", TextArea)
        notes.focus()
        await pilot.pause()
        notes.text = "Discussed roadmap"
        app.query_one("#live-title", TabCompletableInput).focus()
        await pilot.pause()

    assert container.sessions.update_details.call_args.kwargs["notes"] == "Discussed roadmap"


async def test_unrelated_state_change_does_not_clobber_edit() -> None:
    # AC (edge): an unrelated dispatch (e.g. a warning) must not overwrite a field mid-edit.
    sid = uuid4()
    existing = MeetingSession(id=sid, title="Meeting 2026-07-10")
    app, _container = _app_with_live_session(sid, existing)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        title = app.query_one("#live-title", TabCompletableInput)
        title.value = "Half-typed name"
        app.store.dispatch(act.WarningRaised(message="unrelated", at=utc_now()))
        await pilot.pause()
        assert title.value == "Half-typed name"


async def test_fields_disabled_when_no_session() -> None:
    # AC (edge): with no current session the fields are disabled and stop-flush is a no-op.
    sid = uuid4()
    existing = MeetingSession(id=sid, title="Meeting 2026-07-10")
    app, container = _app_with_live_session(sid, existing, with_session=False)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert app.query_one("#live-title", TabCompletableInput).disabled
        await app._save_live_details()
        await pilot.pause()

    container.sessions.update_details.assert_not_called()
