"""U8 — relieve Live sidebar density.

The empty errors panel collapses to a compact single line, the Session status
line no longer renders a full UUID (so it fits a narrow sidebar), and the
transcript column gains width versus the baseline 38-wide sidebar.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import UUID

from live_meeting_transcriber.config.settings import Settings
from live_meeting_transcriber.ui.effects.controller import TuiController
from live_meeting_transcriber.ui.state.model import (
    UiErrorState,
    initial_app_state,
)
from live_meeting_transcriber.ui.state.selectors import (
    build_live_status_lines,
    select_errors_compact_summary,
    select_short_session_id,
)
from live_meeting_transcriber.ui.state.store import Store
from live_meeting_transcriber.ui.tui.app import TranscriberApp
from textual.content import Content
from textual.widgets import RichLog, Static

_NOW = datetime(2026, 7, 8, 12, 0, 0, tzinfo=UTC)
_SID = UUID("12345678-1234-5678-1234-567812345678")


def _visible(markup: str) -> str:
    """Rendered width of a markup line, ignoring the markup tags themselves."""
    return Content.from_markup(markup).plain


# --- pure selectors -------------------------------------------------------


def test_short_session_id_is_eight_chars_not_full_uuid() -> None:
    state = initial_app_state().model_copy(update={"current_session_id": _SID})
    short = select_short_session_id(state)
    assert short == "12345678"
    assert str(_SID) != short


def test_short_session_id_dash_when_no_session() -> None:
    assert select_short_session_id(initial_app_state()) == "—"


def test_status_session_line_fits_narrow_sidebar_and_hides_full_uuid() -> None:
    state = initial_app_state().model_copy(
        update={"current_session_id": _SID, "session_title": "Team sync"}
    )
    lines = build_live_status_lines(state, _NOW)
    # The full UUID is never rendered anywhere in the Live status block (U7/U8).
    assert str(_SID) not in " ".join(lines)
    session_line = next(line for line in lines if "Session" in line)
    # The visible Session line fits a narrow (≤ 32-wide) sidebar without wrapping.
    assert len(_visible(session_line)) <= 30


def test_build_status_lines_still_reports_title_and_status() -> None:
    state = initial_app_state().model_copy(
        update={"current_session_id": _SID, "session_title": "Team sync"}
    )
    joined = "\n".join(build_live_status_lines(state, _NOW))
    assert "Team sync" in joined
    assert "Status" in joined


def test_errors_compact_summary_when_no_errors_or_warnings() -> None:
    summary = select_errors_compact_summary(initial_app_state())
    assert summary is not None
    assert "\n" not in summary  # single line only


def test_errors_compact_summary_none_when_unacked_error() -> None:
    err = UiErrorState(id="e1", message="boom", at=_NOW)
    state = initial_app_state().model_copy(update={"recent_errors": (err,)})
    assert select_errors_compact_summary(state) is None


def test_errors_compact_summary_none_when_warning() -> None:
    state = initial_app_state().model_copy(update={"warnings": ("low audio",)})
    assert select_errors_compact_summary(state) is None


# --- real layout at 120x40 (Pilot) ---------------------------------------


def _app(**updates: object) -> TranscriberApp:
    container = MagicMock()
    container.sessions.list.return_value = []
    # Healthy audio env so the U10 startup check raises no warning — the compact
    # errors panel only holds when there is genuinely nothing to report.
    container.devices.list_sources.return_value = [object()]
    store = Store(state=initial_app_state().model_copy(update=updates))
    controller = TuiController(store=store, container=container, settings=Settings())
    store.register_effects(controller.handle)
    return TranscriberApp(store=store, container=container, controller=controller)


async def test_empty_errors_panel_is_compact_single_line() -> None:
    app = _app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        errors = app.query_one("#errors", Static)
        # Baseline rendered a bordered panel ~17 rows tall even when empty.
        assert errors.size.height <= 1


async def test_transcript_gains_width_over_baseline() -> None:
    app = _app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        transcript = app.query_one("#transcript", RichLog)
        # Baseline (38-wide sidebar) left the transcript at width 80.
        assert transcript.size.width > 80


async def test_errors_panel_expands_when_error_present() -> None:
    err = UiErrorState(id="e1", message="disk full", at=_NOW)
    app = _app(recent_errors=(err,))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        errors = app.query_one("#errors", Static)
        assert errors.size.height >= 3  # bordered panel showing the message
