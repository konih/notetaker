"""Pure word/turn interval-overlap speaker assignment (F12).

The MLX finalize engine (mlx-whisper) has no wav2vec2 forced alignment, so WhisperX's
``assign_word_speakers`` cannot be reused; instead each word is attributed to the
diarization turn it overlaps most. Productionized from the F11 spike prototype
(``docs/spikes/f11/compare_overlap_assignment.py``), which reproduced the production
speaker attribution at 97.7% word-level agreement on the AMI meeting fixture — see
``docs/spikes/2026-07-11-f11-apple-silicon-asr.md`` §3.

Guards for the spike's measured failure modes:

- **Zero/near-zero-duration words.** mlx-whisper emits words with ``start == end``
  (attention/DTW timestamps); a raw overlap test never matches them. Intervals
  shorter than ``MIN_WORD_SPAN_SECONDS`` are padded symmetrically around their
  midpoint before scoring.
- **Words outside every turn.** Diarization turns do not cover all speech (VAD gaps,
  overlapping talk); a word overlapping no turn falls back to the *nearest* turn by
  gap distance (ties: earliest turn) instead of dropping the label.

Domain-pure: stdlib only, no provider imports, no I/O.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

#: Minimum interval span (seconds) used for overlap scoring; shorter intervals are
#: padded around their midpoint (the spike's zero-duration-word guard).
MIN_WORD_SPAN_SECONDS = 0.05


@dataclass(frozen=True)
class SpeakerTurn:
    """One diarization turn: ``speaker`` talked from ``start`` to ``end`` (audio seconds)."""

    start: float
    end: float
    speaker: str


def _padded(start: float, end: float, min_span: float) -> tuple[float, float]:
    if end - start >= min_span:
        return start, end
    mid = (start + end) / 2.0
    half = min_span / 2.0
    return mid - half, mid + half


def _gap_to(start: float, end: float, turn: SpeakerTurn) -> float:
    """Distance between ``[start, end]`` and ``turn`` (0.0 when they touch/overlap)."""
    return max(turn.start - end, start - turn.end, 0.0)


def assign_speaker_by_overlap(
    start: float,
    end: float,
    turns: Sequence[SpeakerTurn],
    *,
    min_span: float = MIN_WORD_SPAN_SECONDS,
) -> str | None:
    """Speaker whose turn overlaps ``[start, end]`` most; nearest turn when none overlaps.

    Returns ``None`` only when ``turns`` is empty. The interval is padded to at least
    ``min_span`` seconds around its midpoint first (zero-duration-word guard).
    """
    if not turns:
        return None
    s, e = _padded(float(start), float(end), min_span)
    best: str | None = None
    best_overlap = 0.0
    for turn in turns:
        overlap = min(e, turn.end) - max(s, turn.start)
        if overlap > best_overlap:
            best, best_overlap = turn.speaker, overlap
    if best is not None:
        return best
    nearest = min(turns, key=lambda t: (_gap_to(s, e, t), t.start))
    return nearest.speaker


def assign_segment_speaker(
    *,
    start: float,
    end: float,
    words: Sequence[tuple[float, float]],
    turns: Sequence[SpeakerTurn],
    min_span: float = MIN_WORD_SPAN_SECONDS,
) -> str | None:
    """Segment speaker as a duration-weighted vote over its words' per-word assignment.

    Each word votes for :func:`assign_speaker_by_overlap` of its own interval, weighted
    by its (padded) duration — a long word counts for more than a backchannel blip.
    Segments without word timestamps fall back to assigning the whole segment interval.
    Returns ``None`` only when ``turns`` is empty. Ties resolve deterministically to the
    speaker that first accumulated the winning weight (input order).
    """
    if not turns:
        return None
    weights: dict[str, float] = {}
    for w_start, w_end in words:
        speaker = assign_speaker_by_overlap(w_start, w_end, turns, min_span=min_span)
        if speaker is None:  # pragma: no cover - turns is non-empty here
            continue
        s, e = _padded(float(w_start), float(w_end), min_span)
        weights[speaker] = weights.get(speaker, 0.0) + (e - s)
    if not weights:
        return assign_speaker_by_overlap(start, end, turns, min_span=min_span)
    return max(weights.items(), key=lambda kv: kv[1])[0]
