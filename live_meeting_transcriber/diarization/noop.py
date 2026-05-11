from __future__ import annotations

from live_meeting_transcriber.domain.models import AudioChunk, DiarizationSegment


class NoopDiarizationProvider:
    async def diarize_chunk(self, *, chunk: AudioChunk) -> list[DiarizationSegment]:
        return []
