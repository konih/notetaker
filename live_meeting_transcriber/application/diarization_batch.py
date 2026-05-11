"""Batch diarization for stored sessions (offline reprocessing)."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from uuid import UUID

from live_meeting_transcriber.diarization.merge_service import (
    merge_diarization_into_transcript_segment,
)
from live_meeting_transcriber.domain.models import AudioChunk, DiarizationSegment, TranscriptSegment
from live_meeting_transcriber.domain.ports import (
    DiarizationProvider,
    DiarizationRepository,
    TranscriptRepository,
)


async def reprocess_session_diarization(
    *,
    transcripts: TranscriptRepository,
    diarizer: DiarizationProvider,
    diarization_repo: DiarizationRepository,
    chunk_dir: Path,
    session_id: UUID,
    sample_rate_hz: int = 16000,
    channels: int = 1,
) -> tuple[int, int]:
    """Re-run diarization on WAV files under ``chunk_dir`` for the session.

    Returns ``(chunks_with_audio_processed, transcript_segments_updated)``.
    """
    segments = transcripts.list_by_session(session_id)
    by_chunk: defaultdict[UUID, list[TranscriptSegment]] = defaultdict(list)
    for s in segments:
        if s.chunk_id is None:
            continue
        by_chunk[s.chunk_id].append(s)

    all_diar: list[DiarizationSegment] = []
    chunks_ok = 0
    updated = 0

    for chunk_id in sorted(by_chunk.keys(), key=lambda cid: by_chunk[cid][0].started_at):
        path = chunk_dir / f"{chunk_id}.wav"
        if not path.is_file():
            continue
        segs = by_chunk[chunk_id]
        t0 = min(s.started_at for s in segs)
        t1 = max(s.ended_at for s in segs)
        chunk = AudioChunk(
            id=chunk_id,
            session_id=session_id,
            started_at=t0,
            ended_at=t1,
            path=path,
            sample_rate_hz=sample_rate_hz,
            channels=channels,
        )
        diar_segs = await diarizer.diarize_chunk(chunk=chunk)
        all_diar.extend(diar_segs)
        chunks_ok += 1
        for seg in segs:
            merged = merge_diarization_into_transcript_segment(seg, diar_segs)
            transcripts.update_segment_speaker(seg.id, merged.speaker)
            updated += 1

    if all_diar:
        diarization_repo.replace_for_session(session_id, all_diar)

    return chunks_ok, updated
