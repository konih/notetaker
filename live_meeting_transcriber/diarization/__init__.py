"""Speaker diarization adapters (optional pyannote) and merge helpers."""

from live_meeting_transcriber.diarization.labels import normalize_pyannote_speaker_label
from live_meeting_transcriber.diarization.merge_service import (
    merge_diarization_into_transcript_segment,
    overlap_seconds,
    pick_speaker_by_overlap,
)
from live_meeting_transcriber.diarization.noop import NoopDiarizationProvider

__all__ = [
    "NoopDiarizationProvider",
    "merge_diarization_into_transcript_segment",
    "normalize_pyannote_speaker_label",
    "overlap_seconds",
    "pick_speaker_by_overlap",
]
