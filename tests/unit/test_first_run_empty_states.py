"""U10 — first-run and empty states.

Fresh launches and empty data views tell the user what to do next instead of
showing blank panes, and a non-blocking startup check surfaces missing audio
prerequisites as an actionable warning (never blocks launch).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

from live_meeting_transcriber.config.settings import Settings
from live_meeting_transcriber.domain.models import MeetingSession
from live_meeting_transcriber.ui.effects.controller import TuiController
from live_meeting_transcriber.ui.state.model import (
    TranscriptLineState,
    initial_app_state,
)
from live_meeting_transcriber.ui.state.store import Store
from live_meeting_transcriber.ui.tui.app import SessionsScreen, TranscriberApp
from live_meeting_transcriber.ui.tui.empty_states import (
    LIVE_EMPTY_HINT,
    MEETINGS_EMPTY_HINT,
    SESSIONS_EMPTY_HINT,
    audio_prerequisite_warnings,
)
from textual.content import Content
from textual.widgets import RichLog, Static, TabbedContent

_NOW = datetime(2026, 7, 8, 12, 0, 0, tzinfo=UTC)


# --- pure: startup prerequisite checks -----------------------------------


def test_audio_warnings_when_probe_raises() -> None:
    def _boom() -> list[object]:
        raise RuntimeError("ffmpeg missing")

    warnings = audio_prerequisite_warnings(_boom)
    assert len(warnings) == 1
    assert "ffmpeg" in warnings[0].lower() or "probing failed" in warnings[0].lower()


def test_audio_warnings_when_no_devices() -> None:
    warnings = audio_prerequisite_warnings(lambda: [])
    assert len(warnings) == 1
    assert "no audio" in warnings[0].lower()


def test_audio_warnings_empty_when_devices_present() -> None:
    assert audio_prerequisite_warnings(lambda: [object()]) == []


# --- pure: empty-state copy is actionable --------------------------------


def _plain(markup: str) -> str:
    return Content.from_markup(markup).plain.lower()


def test_empty_hints_name_a_next_action() -> None:
    assert "r" in _plain(LIVE_EMPTY_HINT) and "record" in _plain(LIVE_EMPTY_HINT)
    assert "record" in _plain(MEETINGS_EMPTY_HINT) or "import" in _plain(MEETINGS_EMPTY_HINT)
    assert "live" in _plain(SESSIONS_EMPTY_HINT) or "record" in _plain(SESSIONS_EMPTY_HINT)


# --- live app (Pilot) ----------------------------------------------------


def _app(**updates: object) -> TranscriberApp:
    container = MagicMock()
    container.sessions.list.return_value = []
    # Healthy audio env by default so the startup check stays quiet.
    container.devices.list_sources.return_value = [object()]
    store = Store(state=initial_app_state().model_copy(update=updates))
    controller = TuiController(store=store, container=container, settings=Settings())
    store.register_effects(controller.handle)
    return TranscriberApp(store=store, container=container, controller=controller)


def _richlog_text(log: RichLog) -> str:
    return "\n".join(strip.text for strip in log.lines)


async def test_live_transcript_shows_hint_when_no_segments() -> None:
    app = _app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        transcript = app.query_one("#transcript", RichLog)
        text = _richlog_text(transcript)
        assert "record" in text.lower()


async def test_live_transcript_hint_replaced_by_segments() -> None:
    seg = TranscriptLineState(
        id="s1",
        session_id=str(uuid4()),
        started_at=_NOW,
        ended_at=_NOW,
        text="Hello everyone",
        speaker="speaker_1",
    )
    app = _app(recent_transcript_segments=(seg,))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        transcript = app.query_one("#transcript", RichLog)
        text = _richlog_text(transcript)
        assert "Hello everyone" in text
        assert "Press" not in text  # the first-run hint is gone once there is content


async def test_startup_warns_when_no_audio_devices() -> None:
    container = MagicMock()
    container.sessions.list.return_value = []
    container.devices.list_sources.return_value = []
    app = _browser_app(container)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert any("no audio" in w.lower() for w in app.store.get_state().warnings)


async def test_startup_does_not_block_launch_on_probe_failure() -> None:
    container = MagicMock()
    container.sessions.list.return_value = []
    container.devices.list_sources.side_effect = RuntimeError("no ffmpeg")
    app = _browser_app(container)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        # App still launched and rendered despite the failing probe.
        assert app.query_one("#transcript", RichLog) is not None
        assert app.store.get_state().warnings  # a remediation warning was surfaced


# --- Meetings / Sessions empty states ------------------------------------


def _browser_app(container: MagicMock) -> TranscriberApp:
    store = Store(state=initial_app_state())
    controller = TuiController(store=store, container=container, settings=Settings())
    store.register_effects(controller.handle)
    return TranscriberApp(store=store, container=container, controller=controller)


async def test_meetings_empty_shows_first_run_hint(tmp_path: Path) -> None:
    container = MagicMock()
    container.sessions.list.return_value = []
    container.devices.list_sources.return_value = [object()]
    container.settings.ensure_data_dir.return_value = tmp_path
    app = _browser_app(container)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.query_one(TabbedContent).active = "tab-meetings"
        await pilot.pause()
        status = str(app.query_one("#meeting-detail-status", Static).render())
        assert "record" in status.lower() or "import" in status.lower()


async def test_meetings_shows_detail_when_sessions_exist(tmp_path: Path) -> None:
    session = MeetingSession(id=uuid4(), title="Weekly sync")
    container = MagicMock()
    container.sessions.list.return_value = [session]
    container.sessions.get.return_value = session
    container.summaries.get_by_session.return_value = None
    container.transcripts.list_by_session.return_value = []
    container.session_speakers.get_map.return_value = {}
    container.devices.list_sources.return_value = [object()]
    container.settings.ensure_data_dir.return_value = tmp_path
    app = _browser_app(container)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.query_one(TabbedContent).active = "tab-meetings"
        await pilot.pause()
        status = str(app.query_one("#meeting-detail-status", Static).render())
        # The first-run hint must not be shown when there is a meeting to browse.
        assert MEETINGS_EMPTY_HINT[:20] not in status


async def test_sessions_modal_empty_shows_hint() -> None:
    app = _app()  # sessions_catalog is empty in initial state
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        screen = SessionsScreen()
        app.push_screen(screen)
        await pilot.pause()
        hint = str(screen.query_one("#sessions-empty", Static).render())
        assert hint.strip() != ""
        assert "live" in hint.lower() or "record" in hint.lower()
