"""U18 — state-driven Summary-context modal actions.

Acceptance:
- Empty context no longer presents two equivalent actions (with an empty text box,
  "Summarize" and "Summarize without context" both dismissed with ``""``).
- Button labels/states reflect the current context input.
- The summarization flow stays backward compatible: dismiss with the stripped
  context string ("" = no context) or ``None`` on cancel.

Also guards that the modal no longer advertises the dead ``ctrl+enter`` chord
(terminals without the kitty keyboard protocol collapse it onto Enter, so the
binding silently never fires — same failure mode as the Speaker ID P0).
"""

from __future__ import annotations

from live_meeting_transcriber.ui.tui.meeting_modals import SummaryContextModal
from textual.app import App
from textual.widgets import Button, Static, TextArea


class _HostApp(App[None]):
    def __init__(self, initial: str = "") -> None:
        super().__init__()
        self._initial = initial
        self.results: list[str | None] = []

    async def on_mount(self) -> None:
        await self.push_screen(SummaryContextModal(initial=self._initial), callback=self._done)

    def _done(self, result: str | None) -> None:
        self.results.append(result)


def _primary(app: App[None]) -> Button:
    return app.screen.query_one("#summary-submit", Button)


def _secondary(app: App[None]) -> Button:
    return app.screen.query_one("#summary-without-context", Button)


# --- empty context: a single summarize action -----------------------------------


async def test_empty_context_presents_single_enabled_summarize_action() -> None:
    async with _HostApp().run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        assert str(_primary(pilot.app).label) == "Summarize"
        assert _secondary(pilot.app).disabled is True


async def test_typing_context_enables_secondary_and_relabels_primary() -> None:
    async with _HostApp().run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        await pilot.press("f", "o", "c", "u", "s")
        await pilot.pause()
        assert str(_primary(pilot.app).label) == "Summarize with context"
        assert _secondary(pilot.app).disabled is False


async def test_clearing_context_returns_to_single_action() -> None:
    async with _HostApp(initial="scratch notes").run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        area = pilot.app.screen.query_one("#summary-context-area", TextArea)
        area.text = ""
        await pilot.pause()
        assert str(_primary(pilot.app).label) == "Summarize"
        assert _secondary(pilot.app).disabled is True


async def test_whitespace_only_context_counts_as_empty() -> None:
    async with _HostApp(initial="   \n  ").run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        assert str(_primary(pilot.app).label) == "Summarize"
        assert _secondary(pilot.app).disabled is True


async def test_prefilled_notes_start_in_with_context_state() -> None:
    async with _HostApp(initial="Agenda: roadmap, hiring").run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        assert str(_primary(pilot.app).label) == "Summarize with context"
        assert _secondary(pilot.app).disabled is False


# --- dismissal contract stays backward compatible --------------------------------


async def test_primary_button_dismisses_with_stripped_context() -> None:
    app = _HostApp(initial="  focus on budget  ")
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        await pilot.click("#summary-submit")
        await pilot.pause()
        assert app.results == ["focus on budget"]


async def test_secondary_button_dismisses_with_empty_context() -> None:
    app = _HostApp(initial="focus on budget")
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        await pilot.click("#summary-without-context")
        await pilot.pause()
        assert app.results == [""]


async def test_empty_primary_dismisses_with_empty_context() -> None:
    app = _HostApp()
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        await pilot.click("#summary-submit")
        await pilot.pause()
        assert app.results == [""]


async def test_escape_dismisses_with_none() -> None:
    app = _HostApp(initial="focus")
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert app.results == [None]


# --- working submit key replaces the dead ctrl+enter chord ------------------------


def test_modal_binds_no_dead_ctrl_enter_chord() -> None:
    keys = [
        k.strip()
        for binding in SummaryContextModal.BINDINGS
        for k in str(getattr(binding, "key", "")).split(",")
    ]
    assert not any(k in ("ctrl+enter", "ctrl+return") for k in keys), keys
    submit_keys = [
        k
        for binding in SummaryContextModal.BINDINGS
        for k in str(getattr(binding, "key", "")).split(",")
        if getattr(binding, "action", "") == "submit"
    ]
    assert submit_keys == ["ctrl+s"], submit_keys


async def test_ctrl_s_submits_and_hint_matches() -> None:
    app = _HostApp(initial="focus")
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        hints = [str(w.render()) for w in app.screen.query(Static)]
        assert all("ctrl+enter" not in h.lower() for h in hints), hints
        assert any("ctrl+s" in h.lower() for h in hints), hints
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert app.results == ["focus"]
