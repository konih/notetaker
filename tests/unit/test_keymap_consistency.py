"""U12 — consolidated keybindings: one canonical shortcut per action, agreeing hints.

Acceptance:
- No action has conflicting shortcuts in different UI regions (e.g. Summarize used
  to be ``k`` in the global footer but ``ctrl+g`` on the Meetings tab).
- Help/footer/inline hints render the same key per action.
- Existing high-frequency workflows remain single-key.

The two persistent UI regions are the global app scope (``FOOTER_ACTIONS`` →
``TranscriberApp.BINDINGS``) and the Meetings tab (``MeetingBrowser.BINDINGS``) —
exactly the two sections the ``?`` help overlay projects. Modal screens (confirm
dialogs, slide preview, …) are self-contained scopes with their own footers and are
only covered by the terminal-alias guard below.

Operator decision UX-OQ-3 (2026-07-10): the canonical Summarize key is ``k`` (the
shipped footer binding); ``ctrl+g`` is purged.
"""

from __future__ import annotations

import importlib
import pkgutil
import re
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

from live_meeting_transcriber.config.settings import Settings
from live_meeting_transcriber.domain.models import MeetingSession
from live_meeting_transcriber.ui.effects.controller import TuiController
from live_meeting_transcriber.ui.state.model import initial_app_state
from live_meeting_transcriber.ui.state.store import Store
from live_meeting_transcriber.ui.tui.app import TranscriberApp
from live_meeting_transcriber.ui.tui.footer_bindings import FOOTER_ACTIONS
from live_meeting_transcriber.ui.tui.meeting_browser import (
    MeetingBrowser,
    _format_summary_for_editor,
)
from textual.widgets import Static, TabbedContent

# Textual key names that terminals without the kitty keyboard protocol collapse
# onto a differently-named key, so a Binding on them silently never fires.
# ctrl+i→Tab is the alias that caused the Speaker ID P0; ctrl+enter/ctrl+return
# are indistinguishable from Enter (U25 — same class), so a chord on them is dead
# on standard terminals too.
TERMINAL_ALIASED_KEYS = {"ctrl+i", "ctrl+m", "ctrl+h", "ctrl+enter", "ctrl+return"}


def _pairs(bindings: object) -> list[tuple[str, str, str]]:
    """(key, action, description) per Binding-like entry, splitting comma chords."""
    out: list[tuple[str, str, str]] = []
    for b in bindings:  # type: ignore[attr-defined]
        key = getattr(b, "key", None)
        action = getattr(b, "action", None)
        if key is None or action is None:
            continue
        description = str(getattr(b, "description", "") or "")
        for k in str(key).split(","):
            out.append((k.strip(), str(action), description))
    return out


def _plain(markup: str) -> str:
    """Strip console markup tags so hints can be matched as plain text."""
    return re.sub(r"\[/?[^\[\]]*\]", "", markup)


GLOBAL = _pairs(TranscriberApp.BINDINGS)
MEETINGS = _pairs(MeetingBrowser.BINDINGS)


def _canonical_summarize_key() -> str:
    return next(a.key for a in FOOTER_ACTIONS if a.action == "summarize")


# --- one canonical shortcut per action ---------------------------------------


def test_canonical_summarize_key_is_k() -> None:
    # UX-OQ-3 pin: the operator chose `k` (single-key, already in the footer).
    assert _canonical_summarize_key() == "k"


def test_meetings_tab_does_not_rebind_summarize() -> None:
    # The global `k` action is tab-aware (summarizes the selected meeting on the
    # Meetings tab), so a second Meetings-local Summarize key is a conflict.
    rebound = [(k, a) for k, a, _ in MEETINGS if "summarize" in a]
    assert rebound == [], f"Meetings tab rebinds Summarize: {rebound}"
    bound_keys = {k for k, _, _ in GLOBAL} | {k for k, _, _ in MEETINGS}
    assert "ctrl+g" not in bound_keys, "ctrl+g was purged by UX-OQ-3"


def test_one_key_per_action_across_regions() -> None:
    # An action (identified by its user-facing description) must not answer to
    # different keys in different regions — that is exactly the Summarize bug.
    keys_by_label: dict[str, set[str]] = {}
    for k, _, label in GLOBAL + MEETINGS:
        if label:
            keys_by_label.setdefault(label, set()).add(k)
    conflicts = {label: keys for label, keys in keys_by_label.items() if len(keys) > 1}
    assert conflicts == {}, f"actions with more than one shortcut: {conflicts}"


# --- no duplicate / shadowed shortcut registration ----------------------------


def test_no_duplicate_keys_within_each_region() -> None:
    for name, pairs in (("global", GLOBAL), ("meetings", MEETINGS)):
        keys = [k for k, _, _ in pairs]
        dupes = {k for k in keys if keys.count(k) > 1}
        assert dupes == set(), f"{name} scope binds a key twice: {dupes}"


def test_shared_keys_mean_the_same_action() -> None:
    # A key bound in both regions must mean the same thing (e.g. ctrl+d is
    # Speaker ID in both). A priority Meetings binding on a global key otherwise
    # silently shadows the global action on that tab — `m` used to open the
    # More-actions menu there while the footer catalog promised Sessions.
    global_by_key = {k: label for k, _, label in GLOBAL}
    conflicts = {
        k: (global_by_key[k], label)
        for k, _, label in MEETINGS
        if k in global_by_key and global_by_key[k] != label
    }
    assert conflicts == {}, f"key means different things per region: {conflicts}"


def test_no_terminal_aliased_chords_in_any_tui_bindings() -> None:
    # Sweep every BINDINGS list in ui.tui (screens and modals included): a
    # ctrl+i / ctrl+m / ctrl+h chord never fires on standard terminals.
    package = importlib.import_module("live_meeting_transcriber.ui.tui")
    offenders: list[str] = []
    for mod_info in pkgutil.iter_modules(package.__path__):
        module = importlib.import_module(f"{package.__name__}.{mod_info.name}")
        for attr_name in dir(module):
            obj = getattr(module, attr_name)
            if not isinstance(obj, type) or obj.__module__ != module.__name__:
                continue
            for k, action, _ in _pairs(obj.__dict__.get("BINDINGS", ())):
                if k in TERMINAL_ALIASED_KEYS:
                    offenders.append(f"{module.__name__}.{attr_name}: {k} → {action}")
    assert offenders == [], f"terminal-aliased chords never fire: {offenders}"


# --- high-frequency workflows stay single-key ---------------------------------


def test_core_recording_workflow_stays_single_key() -> None:
    core = {a.action: a.key for a in FOOTER_ACTIONS if a.core}
    for action in ("record", "stop", "summarize", "export_md", "quit"):
        assert action in core, f"{action} left the core footer"
        assert len(core[action]) == 1, f"{action} is no longer single-key: {core[action]}"


# --- inline hints agree with the canonical keymap ------------------------------


def test_summary_editor_placeholder_uses_canonical_key() -> None:
    placeholder = _format_summary_for_editor(None)
    assert "ctrl+g" not in placeholder
    assert f"Press {_canonical_summarize_key()} to generate" in placeholder


def _make_app(container: MagicMock) -> TranscriberApp:
    store = Store(state=initial_app_state())
    controller = TuiController(store=store, container=container, settings=Settings())
    store.register_effects(controller.handle)
    return TranscriberApp(store=store, container=container, controller=controller)


def _mock_container(tmp_path: Path, session: MeetingSession) -> MagicMock:
    container = MagicMock()
    container.sessions.list.return_value = [session]
    container.sessions.get.return_value = session
    container.summaries.get_by_session.return_value = None
    container.transcripts.list_by_session.return_value = []
    container.session_speakers.get_map.return_value = {}
    container.settings.ensure_data_dir.return_value = tmp_path
    container.devices.list_sources.return_value = [object()]
    return container


async def test_meetings_inline_hints_render_canonical_keys(tmp_path: Path) -> None:
    session = MeetingSession(id=uuid4(), title="Weekly sync")
    app = _make_app(_mock_container(tmp_path, session))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.query_one(TabbedContent).active = "tab-meetings"
        await pilot.pause()
        browser = app.query_one(MeetingBrowser)
        texts = [_plain(str(w.render())) for w in browser.query(Static)]

        # No inline hint anywhere on the tab references the purged chord.
        assert all("ctrl+g" not in t for t in texts), texts

        # U14 removed the header's per-action key hints (the header was a third
        # affordance layer on top of the toolbar and footer/help); the remaining
        # inline hint on this tab must still render the canonical key. Header
        # coverage lives in test_meeting_affordance_layers.py.
        key = _canonical_summarize_key()
        summary_hint = next(t for t in texts if "AI summary" in t)
        assert f"({key} to generate)" in summary_hint, summary_hint
