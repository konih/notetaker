from __future__ import annotations

from live_meeting_transcriber.domain.models import TranscriptSegment


class NoopDiarizationProvider:
    async def diarize(self, *, segment: TranscriptSegment) -> TranscriptSegment:
        return segment

