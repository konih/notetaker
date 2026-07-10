from __future__ import annotations

from datetime import datetime, tzinfo

from live_meeting_transcriber.domain.speaker_display import format_transcript_speaker_label
from live_meeting_transcriber.ui.state.model import (
    AppState,
    RecordingStatus,
    TranscriptionStatus,
    TranscriptLineState,
    UiErrorState,
)
from live_meeting_transcriber.utils.time import elapsed_seconds, format_clock, format_duration


def select_header_title(state: AppState) -> str:
    base = state.session_title or "No session"
    if state.recording_status == RecordingStatus.recording:
        return f"⏺ {base}"
    if state.recording_status == RecordingStatus.starting:
        return f"◯ {base}"
    if state.recording_status == RecordingStatus.stopping:
        return f"⏹ {base}"
    return base


def select_decayed_level(state: AppState, now: datetime) -> float | None:
    """Last chunk peak decayed toward zero since it was captured (U13).

    The meter is fed one peak per audio chunk (~every ``chunk_seconds``). Holding that
    value between updates freezes the bar on a stale "loud" reading — during silence or
    after stop it keeps implying live audio. Linearly decaying it over the chunk window
    makes it honest: a re-armed peak each chunk keeps active speech high, while silence
    lets the bar fall off. Returns ``None`` when idle or before the first reading.
    """
    if state.recording_status != RecordingStatus.recording:
        return None
    if state.current_level_meter is None or state.last_level_at is None:
        return None
    window = max(float(state.chunk_seconds), 1.0)
    elapsed = (now - state.last_level_at).total_seconds()
    factor = max(0.0, 1.0 - elapsed / window)
    return state.current_level_meter * factor


def select_level_bar(state: AppState, now: datetime | None = None, width: int = 12) -> str:
    """ASCII level meter from last chunk peak (updates each chunk, not sample-accurate).

    Pass ``now`` to decay the reading between chunk updates (U13); omit it for the raw,
    non-decaying peak (callers without a wall clock).
    """
    level = select_decayed_level(state, now) if now is not None else state.current_level_meter
    if level is None:
        return "—"
    filled = min(width, max(0, round(level * width)))
    return f"{'█' * filled}{'░' * (width - filled)}"


def select_is_recording(state: AppState) -> bool:
    return state.recording_status == RecordingStatus.recording


def select_unacknowledged_errors(state: AppState) -> tuple[UiErrorState, ...]:
    return tuple(e for e in state.recent_errors if not e.acknowledged)


def select_display_speaker(state: AppState, speaker_key: str) -> str:
    return format_transcript_speaker_label(speaker_key, state.speaker_aliases)


def select_transcript_timestamp(line: TranscriptLineState, tz: tzinfo | None = None) -> str:
    """Compact local wall-clock start time (``HH:MM:SS``) for a transcript line.

    Replaces the full ISO ``started → ended`` range that ate transcript width and
    truncated speech. Start time alone is enough to place a line in the meeting.
    """
    return format_clock(line.started_at, tz)


_RECORDING_LABELS = {
    RecordingStatus.recording: "● Recording",
    RecordingStatus.starting: "◯ Starting…",
    RecordingStatus.stopping: "■ Stopping…",
    RecordingStatus.stopped: "Stopped",
    RecordingStatus.failed: "Recording failed",
    RecordingStatus.idle: "Idle",
}


def _speakers_label(state: AppState) -> str:
    """Plain-language description of how live audio is captured for speaker separation."""
    if state.audio_channels >= 2:
        if state.audio_stereo_mode.strip().lower() == "dual_path":
            return "Speaker split: you vs. remote"
        return "Stereo (mixed)"
    return "Single channel"


def select_elapsed_label(state: AppState, now: datetime) -> str | None:
    """Elapsed recording time (``MM:SS`` / ``H:MM:SS``) while recording, else ``None``.

    ``now`` is passed in (not read internally) so the caller owns the clock and tests
    stay deterministic. Returns ``None`` unless actively recording with a known start.
    """
    if state.recording_status != RecordingStatus.recording or state.recording_started_at is None:
        return None
    return format_duration(elapsed_seconds(state.recording_started_at, now))


def select_short_session_id(state: AppState) -> str:
    """First 8 hex chars of the current session UUID (retrieval hint), or ``—``.

    The full UUID used to be rendered in the Live sidebar, wrapping onto a second
    line and duplicating the identity already carried by the meeting title. A short
    prefix is enough to correlate a live meeting with a Sessions-modal row (U8/U7).
    """
    sid = state.current_session_id
    return "—" if sid is None else str(sid)[:8]


def select_errors_compact_summary(state: AppState) -> str | None:
    """Single-line "all clear" indicator when there is nothing to show, else ``None``.

    Returning ``None`` signals the caller to render the full errors/warnings panel;
    a non-``None`` string is a compact one-liner that lets the sidebar reclaim the
    rows the empty bordered panel used to occupy (U8).
    """
    if select_unacknowledged_errors(state) or state.warnings:
        return None
    return "✓ No errors or warnings"


def build_live_status_lines(state: AppState, now: datetime) -> list[str]:
    """Rich-markup lines for the Live sidebar status block (pure, testable).

    Extracted from ``TranscriberApp._render_status`` so the density rules (short
    session id, compact labels) can be asserted without mounting the app (U8).
    ``now`` is passed in so the elapsed line is deterministic in tests.
    """
    log_hint = (
        state.log_file_path[:52] + "…" if len(state.log_file_path) > 55 else state.log_file_path
    )
    decayed_level = select_decayed_level(state, now)
    peak_pct = f"{decayed_level * 100:.0f}%" if decayed_level is not None else "—"
    lines = [
        f"[bold]Session[/] {select_short_session_id(state)}",
        f"[bold]Title[/] {state.session_title or '—'}",
        f"[bold]Status[/] {select_status_line(state)}",
    ]
    elapsed = select_elapsed_label(state, now)
    if elapsed is not None:
        lines.append(f"[bold]Elapsed[/] {elapsed}")
    lines += [
        f"[bold]Level[/] [{select_level_bar(state, now)}] {peak_pct} [dim](per chunk)[/]",
        f"[bold]Chunk[/] {state.chunk_seconds}s",
        f"[bold]Source[/] {state.audio_source or 'default monitor'} [dim](a: change)[/]",
        f"[bold]Mic[/] {state.microphone_source or state.configured_microphone_source or ('—' if not state.audio_include_microphone else 'default')}",
        f"[bold]Log[/] {log_hint or '—'}",
        f"[bold]Sessions[/] {len(state.sessions_catalog)} in DB"
        + (" (loading…)" if state.sessions_loading else ""),
        f"[bold]Live speakers[/] {state.audio_stereo_mode} ({state.audio_channels}ch)"
        + (
            f" · heard: {', '.join(sorted(state.diarization_detected_speakers))}"
            if state.diarization_detected_speakers
            else ""
        ),
        f"[bold]Finalize[/] auto={state.finalize_on_session_stop} · HF={state.hf_token_configured}",
    ]
    return lines


def select_status_line(state: AppState) -> str:
    """One-line, plain-language recording status for the Live sidebar.

    Speaks the user's language, not the code's: no ``rec=``/``asr=``/``live_spk=``/``diar_ui=``
    internal keys. Detected speakers ("heard") and audio source are intentionally *not*
    repeated here — they have dedicated sidebar lines, so surfacing them again would duplicate.
    """
    parts = [_RECORDING_LABELS.get(state.recording_status, "Idle")]

    ts = state.transcription_status
    if ts == TranscriptionStatus.active:
        parts.append("transcribing")
    elif ts == TranscriptionStatus.degraded:
        parts.append("transcription degraded")
    elif ts == TranscriptionStatus.failed:
        parts.append("transcription failed")

    parts.append(_speakers_label(state))
    return " · ".join(parts)
