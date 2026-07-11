"""F12: pure word/turn interval-overlap speaker assignment.

Swapping the finalize ASR engine to mlx-whisper loses WhisperX's wav2vec2 forced
alignment, so the speaker-to-word mapping is written here as a pure domain function
(productionized from the F11 spike prototype, 97.7% word-level agreement — see
``docs/spikes/2026-07-11-f11-apple-silicon-asr.md`` §3). The spike's measured failure
mode is guarded explicitly: mlx-whisper emits zero-duration words (start == end) that
would overlap no turn; these are padded around their midpoint, and words that still
overlap nothing fall back to the nearest turn.

Domain-pure: no provider imports, no I/O.
"""

from __future__ import annotations

from live_meeting_transcriber.domain.speaker_overlap import (
    SpeakerTurn,
    assign_segment_speaker,
    assign_speaker_by_overlap,
)

TURNS = [
    SpeakerTurn(start=0.0, end=5.0, speaker="SPEAKER_00"),
    SpeakerTurn(start=6.0, end=10.0, speaker="SPEAKER_01"),
]


# --- single interval ------------------------------------------------------------
def test_word_inside_a_turn_gets_that_speaker() -> None:
    assert assign_speaker_by_overlap(1.0, 2.0, TURNS) == "SPEAKER_00"
    assert assign_speaker_by_overlap(7.0, 8.0, TURNS) == "SPEAKER_01"


def test_word_spanning_two_turns_takes_larger_overlap() -> None:
    assert assign_speaker_by_overlap(3.0, 7.0, TURNS) == "SPEAKER_00"  # 2.0 s vs 1.0 s
    assert assign_speaker_by_overlap(4.5, 9.0, TURNS) == "SPEAKER_01"  # 0.5 s vs 3.0 s


def test_zero_duration_word_is_padded_and_assigned() -> None:
    # The spike's dominant disagreement cause: start == end -> raw overlap is never > 0.
    assert assign_speaker_by_overlap(2.0, 2.0, TURNS) == "SPEAKER_00"
    assert assign_speaker_by_overlap(8.0, 8.0, TURNS) == "SPEAKER_01"


def test_near_zero_duration_word_is_padded() -> None:
    assert assign_speaker_by_overlap(2.0, 2.001, TURNS) == "SPEAKER_00"


def test_word_in_a_gap_falls_back_to_nearest_turn() -> None:
    # 5.1..5.2 overlaps neither turn; nearest is SPEAKER_00 (gap 0.1 vs 0.8).
    assert assign_speaker_by_overlap(5.1, 5.2, TURNS) == "SPEAKER_00"
    # 5.8..5.9 is nearer SPEAKER_01 (gap 0.1 vs 0.8).
    assert assign_speaker_by_overlap(5.8, 5.9, TURNS) == "SPEAKER_01"


def test_zero_duration_word_in_a_gap_falls_back_to_nearest_turn() -> None:
    assert assign_speaker_by_overlap(5.9, 5.9, TURNS) == "SPEAKER_01"


def test_no_turns_returns_none() -> None:
    assert assign_speaker_by_overlap(1.0, 2.0, []) is None


def test_gap_tie_is_deterministic_earliest_turn() -> None:
    turns = [
        SpeakerTurn(start=0.0, end=1.0, speaker="B"),
        SpeakerTurn(start=3.0, end=4.0, speaker="A"),
    ]
    # 2.0 is equidistant (gap 1.0 to both); the earliest turn wins.
    assert assign_speaker_by_overlap(2.0, 2.0, turns) == "B"


# --- segment vote ----------------------------------------------------------------
def test_segment_speaker_is_duration_weighted_word_vote() -> None:
    # Two short words in SPEAKER_00, one long word in SPEAKER_01: duration wins.
    words = [(1.0, 1.2), (1.3, 1.5), (6.5, 9.5)]
    assert assign_segment_speaker(start=1.0, end=9.5, words=words, turns=TURNS) == "SPEAKER_01"


def test_segment_speaker_majority_of_equal_words() -> None:
    words = [(1.0, 1.5), (2.0, 2.5), (7.0, 7.5)]
    assert assign_segment_speaker(start=1.0, end=7.5, words=words, turns=TURNS) == "SPEAKER_00"


def test_segment_without_words_uses_segment_interval() -> None:
    assert assign_segment_speaker(start=6.5, end=9.0, words=[], turns=TURNS) == "SPEAKER_01"


def test_segment_of_zero_duration_words_still_assigned() -> None:
    words = [(2.0, 2.0), (2.5, 2.5)]
    assert assign_segment_speaker(start=2.0, end=2.5, words=words, turns=TURNS) == "SPEAKER_00"


def test_segment_with_no_turns_returns_none() -> None:
    assert assign_segment_speaker(start=0.0, end=1.0, words=[(0.0, 1.0)], turns=[]) is None
