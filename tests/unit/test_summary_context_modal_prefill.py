from __future__ import annotations

from live_meeting_transcriber.ui.tui.meeting_browser import SummaryContextModal
from textual.app import App
from textual.widgets import TextArea


async def test_summary_context_modal_prefills_initial_notes() -> None:
    # U20 AC2: notes set during the live meeting pre-fill the summary-context box so the
    # operator isn't asked for the same context twice.
    initial = "Agenda: roadmap, hiring"

    class _HostApp(App[None]):
        async def on_mount(self) -> None:
            await self.push_screen(SummaryContextModal(initial=initial))

    async with _HostApp().run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        area = pilot.app.screen.query_one("#summary-context-area", TextArea)
        assert area.text == initial


async def test_summary_context_modal_empty_by_default() -> None:
    class _HostApp(App[None]):
        async def on_mount(self) -> None:
            await self.push_screen(SummaryContextModal())

    async with _HostApp().run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        area = pilot.app.screen.query_one("#summary-context-area", TextArea)
        assert area.text == ""
