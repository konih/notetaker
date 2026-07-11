from __future__ import annotations

import math
from datetime import datetime, tzinfo

from live_meeting_transcriber.domain.speaker_display import format_transcript_speaker_label

# Stage ladder lives in its own module so the (import-light) reducer can share it;
# re-exported here because selectors are the UI's one-stop derive-from-state API.
from live_meeting_transcriber.ui.state.finalize_stages import (
    FINALIZE_STAGES as FINALIZE_STAGES,
)
from live_meeting_transcriber.ui.state.finalize_stages import (
    select_finalize_stage_index as select_finalize_stage_index,
)
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
    value indefinitely freezes the bar on a stale "loud" reading — during silence or after
    stop it keeps implying live audio. This is a **peak-hold with delayed decay**: the peak
    is held for one expected chunk interval (so normal, continuous speech does *not* pulse
    full→empty between updates), then falls off linearly to zero over the following interval
    when a chunk is late — i.e. real silence, a stalled capture, or a stopped session.
    Returns ``None`` when idle or before the first reading.
    """
    if state.recording_status != RecordingStatus.recording:
        return None
    if state.current_level_meter is None or state.last_level_at is None:
        return None
    window = max(float(state.chunk_seconds), 1.0)
    elapsed = (now - state.last_level_at).total_seconds()
    # Hold at full for one interval; decay over the next; zero once two intervals stale.
    factor = 1.0 if elapsed <= window else max(0.0, 1.0 - (elapsed - window) / window)
    return state.current_level_meter * factor


def select_chunk_progress_label(state: AppState) -> str | None:
    """Compact per-chunk transcription progress for the Live Audio card (F8).

    ``None`` when idle or before the first chunk lands (nothing to report);
    "#N transcribing…" while chunk N is in the live transcriber, "#N done" between
    chunks. Numbering is 1-based from the operator's point of view.
    """
    if state.recording_status != RecordingStatus.recording:
        return None
    if state.chunk_processing:
        return f"#{state.chunks_processed + 1} transcribing…"
    if state.chunks_processed > 0:
        return f"#{state.chunks_processed} done"
    return None


def select_next_chunk_eta_seconds(state: AppState, now: datetime) -> int | None:
    """Whole seconds until the next audio chunk boundary, or ``None`` when idle (F8).

    Pure: anchored on the last per-chunk level reading (one per captured chunk —
    the same anchor the U13 decay uses), falling back to the recording start
    before the first chunk. Clamped at 0 when a chunk is overdue (slow capture /
    long processing) instead of wrapping — an honest "due now", not a fake restart.
    """
    if state.recording_status != RecordingStatus.recording:
        return None
    anchor = state.last_level_at or state.recording_started_at
    if anchor is None:
        return None
    window = max(float(state.chunk_seconds), 1.0)
    remaining = window - elapsed_seconds(anchor, now)
    return max(0, math.ceil(remaining))


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


def _kv(label: str, value: str, pad: int = 9) -> str:
    """One aligned ``label value`` card line: bold label column, then the value."""
    return f"[bold]{label:<{pad}}[/]{value}"


def build_session_card_lines(state: AppState, now: datetime) -> list[str]:
    """Rich-markup lines for the Live sidebar *Session* card (pure, testable)."""
    lines = [
        _kv("Session", select_short_session_id(state)),
        _kv("Title", state.session_title or "—"),
        _kv("Status", select_status_line(state)),
    ]
    elapsed = select_elapsed_label(state, now)
    if elapsed is not None:
        lines.append(_kv("Elapsed", elapsed))
    return lines


def build_audio_card_lines(state: AppState, now: datetime) -> list[str]:
    """Rich-markup lines for the Live sidebar *Audio* card (pure, testable)."""
    decayed_level = select_decayed_level(state, now)
    peak_pct = f"{decayed_level * 100:.0f}%" if decayed_level is not None else "—"
    mic = state.microphone_source or state.configured_microphone_source
    if mic is None:
        mic = "—" if not state.audio_include_microphone else "default"
    chunk_progress = select_chunk_progress_label(state)
    # While recording the static chunk length gives way to live progress — the
    # countdown already conveys the cadence and the line must not wrap (U8).
    chunk_parts = [chunk_progress] if chunk_progress else [f"{state.chunk_seconds}s"]
    next_eta = select_next_chunk_eta_seconds(state, now)
    if next_eta is not None:
        chunk_parts.append(f"next {next_eta}s")
    return [
        _kv("Level", f"[{select_level_bar(state, now)}] {peak_pct} [dim](per chunk)[/]"),
        _kv("Chunk", " · ".join(chunk_parts)),
        _kv("Source", f"{state.audio_source or 'default monitor'} [dim](a: change)[/]"),
        _kv("Mic", mic),
    ]


def build_pipeline_card_lines(state: AppState) -> list[str]:
    """Rich-markup lines for the Live sidebar *Pipeline* card (pure, testable)."""
    log_hint = (
        state.log_file_path[:52] + "…" if len(state.log_file_path) > 55 else state.log_file_path
    )
    heard = (
        f" · heard: {', '.join(sorted(state.diarization_detected_speakers))}"
        if state.diarization_detected_speakers
        else ""
    )
    return [
        _kv("Log", log_hint or "—"),
        _kv(
            "Sessions",
            f"{len(state.sessions_catalog)} in DB"
            + (" (loading…)" if state.sessions_loading else ""),
        ),
        _kv("Speakers", f"{state.audio_stereo_mode} ({state.audio_channels}ch){heard}"),
        _kv(
            "Finalize",
            f"auto={state.finalize_on_session_stop} · HF={state.hf_token_configured}",
        ),
    ]


def build_live_status_lines(state: AppState, now: datetime) -> list[str]:
    """All Live-sidebar status lines: the three cards, in display order.

    The redesigned sidebar renders the cards separately; this concatenation
    preserves the original single-block contract (density rules, no full UUID —
    U8) so the whole surface can still be asserted in one pass.
    """
    return [
        *build_session_card_lines(state, now),
        *build_audio_card_lines(state, now),
        *build_pipeline_card_lines(state),
    ]


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
