"""P0 — Speaker ID must be runnable from the Meetings tab UI.

Root cause of "I can't run Speaker ID via the UI for past meetings": the only
keyboard trigger was ``ctrl+i``, which on terminals without the kitty keyboard
protocol (macOS Terminal.app included) is byte-identical to Tab (0x09). Textual
reports it as the ``tab`` key, so the ``ctrl+i`` binding never fires — pressing it
just moves focus. Speaker ID was otherwise only reachable through the buried
overflow "More…" menu.

These tests pin the fix: Speaker ID is bound to a key that actually fires (not
``ctrl+i``) and is a visible toolbar button, so a past meeting can be finalized
from the Meetings tab without the CLI.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from live_meeting_transcriber.domain.models import MeetingSession
from live_meeting_transcriber.ui.tui.app import TranscriberApp
from live_meeting_transcriber.ui.tui.meeting_browser import MeetingBrowser
from live_meeting_transcriber.ui.tui.meeting_toolbar import primary_toolbar_actions
from textual.widgets import TabbedContent

from tests.unit.conftest import make_mock_tui_container, make_tui_app

# Keys that terminals collapse onto a differently-named key (no kitty protocol),
# so a Binding on them silently never fires. ctrl+i→Tab is the one that bit us.
_TAB_ALIASED_KEYS = {"ctrl+i"}


def _binding_pairs(bindings: object) -> list[tuple[str, str]]:
    """Return (key, action) for every Binding-like entry, splitting comma chords."""
    pairs: list[tuple[str, str]] = []
    for b in bindings:  # type: ignore[attr-defined]
        key = getattr(b, "key", None)
        action = getattr(b, "action", None)
        if key is None or action is None:
            continue
        for k in str(key).split(","):
            pairs.append((k.strip(), str(action)))
    return pairs


def test_app_speaker_id_binding_is_not_tab_aliased() -> None:
    pairs = _binding_pairs(TranscriberApp.BINDINGS)
    finalize = [(k, a) for k, a in pairs if "finalize" in a]
    assert finalize, "app must bind a Speaker ID / finalize action"
    for k, _ in finalize:
        assert k not in _TAB_ALIASED_KEYS, f"{k} aliases Tab and never fires"


def test_meeting_browser_speaker_id_binding_is_not_tab_aliased() -> None:
    pairs = _binding_pairs(MeetingBrowser.BINDINGS)
    finalize = [(k, a) for k, a in pairs if "finalize" in a]
    assert finalize, "Meetings tab must bind a Speaker ID / finalize action"
    for k, _ in finalize:
        assert k not in _TAB_ALIASED_KEYS, f"{k} aliases Tab and never fires"


def test_speaker_id_is_a_visible_toolbar_button() -> None:
    # Promoting it out of the overflow menu makes it clickable without keyboard.
    primary_ids = {a.button_id for a in primary_toolbar_actions()}
    assert "meeting-btn-speaker-id" in primary_ids


# --- real Pilot: the shortcut fires and Tab does not -----------------------


async def test_speaker_id_shortcut_reaches_finalize_and_tab_does_not(tmp_path: Path) -> None:
    session = MeetingSession(id=uuid4(), title="Past meeting")
    app = make_tui_app(make_mock_tui_container(tmp_path, [session]))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.query_one(TabbedContent).active = "tab-meetings"
        await pilot.pause()
        browser = app.query_one(MeetingBrowser)
        # A row is auto-selected on mount; confirm a session is targetable.
        assert browser.selected_session_id is not None

        calls: list[str] = []

        async def _spy() -> None:
            calls.append("finalize")

        app.action_finalize_speakers = _spy  # type: ignore[method-assign]
        browser.action_finalize_selected_speakers = _spy  # type: ignore[method-assign]

        # Tab must NOT trigger Speaker ID (it only moves focus).
        await pilot.press("tab")
        await pilot.pause()
        assert calls == [], "Tab must not invoke Speaker ID"

        # The real shortcut must fire.
        key = next(
            k
            for k, a in _binding_pairs(MeetingBrowser.BINDINGS)
            if "finalize" in a and k not in _TAB_ALIASED_KEYS
        )
        await pilot.press(key)
        await pilot.pause()
        assert calls == ["finalize"], f"{key} must invoke Speaker ID"
