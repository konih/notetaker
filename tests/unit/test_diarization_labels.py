from __future__ import annotations

from live_meeting_transcriber.diarization.labels import normalize_pyannote_speaker_label
from live_meeting_transcriber.domain.speaker_display import format_transcript_speaker_label


def test_normalize_pyannote_speaker_zero_based() -> None:
    assert normalize_pyannote_speaker_label("SPEAKER_00") == "speaker_1"
    assert normalize_pyannote_speaker_label("SPEAKER_01") == "speaker_2"


def test_format_transcript_speaker_unknown_and_numbered() -> None:
    assert format_transcript_speaker_label("unknown", {}) == "Unknown Speaker"
    assert format_transcript_speaker_label("speaker_1", {}) == "Speaker 1"
    assert format_transcript_speaker_label("speaker_1", {"speaker_1": "Konrad"}) == "Konrad"
