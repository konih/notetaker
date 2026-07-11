"""Pure Rich-markup renderers for the redesigned TUI chrome.

Everything here is a deterministic function of its inputs (no widgets, no
clock reads), so the fancy parts of the UI — the gradient VU meter, the level
sparkline, the recording state pill, the speaker-colored transcript blocks,
the status-deck line — are all unit-testable without mounting the app.
"""

from __future__ import annotations

import zlib
from collections.abc import Sequence
from datetime import datetime

from rich.markup import escape
from rich.text import Text

from live_meeting_transcriber.ui.state.model import AppState, RecordingStatus
from live_meeting_transcriber.ui.state.selectors import (
    FINALIZE_STAGES,
    select_decayed_level,
    select_elapsed_label,
    select_finalize_stage_index,
)
from live_meeting_transcriber.ui.tui.theme import (
    ACCENT,
    LEVEL_HOT,
    LEVEL_OK,
    LEVEL_PEAK,
    PILL_INK,
    SPEAKER_PALETTE,
    STATE_BUSY,
    STATE_FAILED,
    STATE_OK,
    STATE_RECORDING,
)

# Partial-fill glyphs: index 1..8 = 1/8th .. full block (index 0 unused).
_EIGHTHS = " ▏▎▍▌▋▊▉█"
_SPARK = "▁▂▃▄▅▆▇█"
_EMPTY_CELL = "╌"


def _zone_color(position: float) -> str:
    """VU zone color for a cell at ``position`` (0..1 of full scale)."""
    if position < 0.60:
        return LEVEL_OK
    if position < 0.85:
        return LEVEL_HOT
    return LEVEL_PEAK


def _merge_runs(cells: Sequence[tuple[str, str]]) -> str:
    """Collapse per-char ``(style, char)`` pairs into compact Rich markup."""
    out: list[str] = []
    prev_style: str | None = None
    for style, char in cells:
        if style != prev_style:
            if prev_style is not None:
                out.append("[/]")
            out.append(f"[{style}]")
            prev_style = style
        out.append(char)
    if prev_style is not None:
        out.append("[/]")
    return "".join(out)


def vu_bar_markup(level: float | None, width: int = 14) -> str:
    """Gradient VU meter: green → amber → red zones, 1/8th-cell resolution.

    ``None`` (idle / no reading yet) renders a dim empty track so the meter
    keeps its footprint instead of the layout jumping when audio starts.
    """
    if level is None:
        return f"[dim]{_EMPTY_CELL * width}[/]"
    clamped = max(0.0, min(1.0, level))
    eighths = round(clamped * width * 8)
    cells: list[tuple[str, str]] = []
    for i in range(width):
        fill = min(8, max(0, eighths - i * 8))
        if fill:
            cells.append((_zone_color((i + 0.5) / width), _EIGHTHS[fill]))
        else:
            cells.append(("dim", _EMPTY_CELL))
    return _merge_runs(cells)


def sparkline_markup(levels: Sequence[float], width: int = 16) -> str:
    """Recent level history as a sparkline, each column zone-colored by value.

    Shows the newest ``width`` readings right-aligned; missing history pads
    dim on the left so the graph grows in from the right as audio arrives.
    """
    recent = list(levels)[-width:]
    cells: list[tuple[str, str]] = [("dim", "▁")] * (width - len(recent))
    for value in recent:
        clamped = max(0.0, min(1.0, value))
        glyph = _SPARK[min(len(_SPARK) - 1, int(clamped * len(_SPARK)))]
        cells.append((_zone_color(clamped), glyph))
    return _merge_runs(cells)


def state_pill_markup(status: RecordingStatus, *, pulse_on: bool = True) -> str:
    """The status deck's recording-state pill (filled chip, state-colored).

    While recording the glyph alternates ●/○ with ``pulse_on`` so the deck
    visibly "breathes" — an at-a-glance liveness cue no static label gives.
    """
    if status == RecordingStatus.recording:
        glyph = "●" if pulse_on else "○"
        return f"[bold {PILL_INK} on {STATE_RECORDING}] {glyph} REC [/]"
    if status == RecordingStatus.starting:
        return f"[bold {PILL_INK} on {STATE_BUSY}] ◌ STARTING [/]"
    if status == RecordingStatus.stopping:
        return f"[bold {PILL_INK} on {STATE_BUSY}] ■ STOPPING [/]"
    if status == RecordingStatus.stopped:
        return f"[bold {PILL_INK} on {STATE_OK}] ✔ STOPPED [/]"
    if status == RecordingStatus.failed:
        return f"[bold #ffffff on {STATE_FAILED}] ✗ FAILED [/]"
    return "[dim] ○ IDLE [/]"


def speaker_color(speaker_key: str) -> str:
    """Stable chip color for a speaker key (same key → same color, always)."""
    digest = zlib.crc32(speaker_key.encode("utf-8"))
    return SPEAKER_PALETTE[digest % len(SPEAKER_PALETTE)]


def transcript_segment_text(
    *, timestamp: str, speaker_label: str, speaker_key: str, body: str
) -> Text:
    """One live-transcript block: colored speaker gutter+chip, dim time, body.

    Built with :class:`rich.text.Text` assembly — never markup parsing — so
    transcribed speech containing ``[`` can't corrupt or style the log.
    """
    color = speaker_color(speaker_key)
    return Text.assemble(
        ("▍ ", color),
        (speaker_label, f"bold {color}"),
        ("  ", ""),
        (timestamp, "dim"),
        "\n",
        (body, ""),
    )


_DECK_SEP = " [dim]│[/] "

_DECK_TITLE_MAX = 24


def _deck_truncate(text: str, limit: int = _DECK_TITLE_MAX) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def stage_bar_markup(index: int, total: int) -> str:
    """Fixed-width stage-progress bar: one cell per pipeline stage (F8).

    Cell ``index`` (clamped) plus all earlier stages render filled — the current
    stage counts as underway, so a fresh job already shows first-cell progress
    instead of an empty, dead-looking track.
    """
    filled = max(1, min(total, index + 1))
    return f"[{ACCENT}]{'▰' * filled}[/][dim]{'▱' * (total - filled)}[/]"


def finalize_deck_markup(state: AppState) -> str | None:
    """Deck segment for the offline Speaker ID / finalize queue (B7 + F8).

    While a job runs: job title + stage-progress bar + current pipeline stage
    (+ backlog size). After it ends: the outcome *persists* (styled by severity)
    until the next job starts — a multi-minute background job must not vanish
    into a 3s toast or the hidden Logs tab. Returns ``None`` when there is
    nothing to report.
    """
    if state.finalize_active_session_id is not None:
        title = _deck_truncate(state.finalize_active_title or "meeting")
        stage = state.finalize_stage or "starting…"
        bar = stage_bar_markup(
            select_finalize_stage_index(state.finalize_stage), len(FINALIZE_STAGES)
        )
        queued = (
            f" [dim](+{state.finalize_queued_count} queued)[/]"
            if state.finalize_queued_count > 0
            else ""
        )
        return (
            f"[{STATE_BUSY}]⚙ Speaker ID[/] {escape(title)} {bar} [dim]{escape(stage)}[/]{queued}"
        )
    if state.finalize_last_result:
        if state.finalize_last_result_level == "error":
            style, glyph = STATE_FAILED, "✖"
        elif state.finalize_last_result_level == "warning":
            style, glyph = STATE_BUSY, "⚠"
        else:
            style, glyph = STATE_OK, "✓"
        return f"[{style}]{glyph}[/] [dim]{escape(state.finalize_last_result)}[/]"
    return None


def build_deck_markup(state: AppState, now: datetime, *, pulse_on: bool = True) -> str:
    """The status deck's main line: pill · title · elapsed · VU · sparkline · finalize.

    Idle shows only pill + title (quiet chrome); the live metrics join the
    line while recording, and the Speaker ID / finalize job status joins it
    whenever offline work is running or just finished (B7 — the deck is the
    one strip visible from every tab). Pure so the deck widget stays a thin shell.
    """
    parts = [state_pill_markup(state.recording_status, pulse_on=pulse_on)]
    title = state.session_title or "no session"
    parts.append(f"[bold]{escape(title)}[/]")
    elapsed = select_elapsed_label(state, now)
    if elapsed is not None:
        parts.append(f"[{ACCENT}]⏱ {elapsed}[/]")
    if state.recording_status == RecordingStatus.recording:
        level = select_decayed_level(state, now)
        pct = f"{level * 100:3.0f}%" if level is not None else "  —"
        parts.append(f"{vu_bar_markup(level)} [dim]{pct}[/]")
        parts.append(sparkline_markup(state.level_history))
    finalize = finalize_deck_markup(state)
    if finalize is not None:
        parts.append(finalize)
    return _DECK_SEP.join(parts)
