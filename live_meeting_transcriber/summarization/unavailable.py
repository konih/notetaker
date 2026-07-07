from __future__ import annotations

from collections.abc import Iterable

from live_meeting_transcriber.domain.models import MeetingSession, Summary, TranscriptSegment


class UnavailableSummarizationError(RuntimeError):
    pass


class UnavailableSummarizationProvider:
    """Placeholder when summaries are configured but OPENAI_API_KEY is missing."""

    def __init__(self, *, reason: str) -> None:
        self._reason = reason

    async def summarize(
        self,
        *,
        session: MeetingSession,
        segments: Iterable[TranscriptSegment],
        speaker_display: dict[str, str] | None = None,
        user_context: str | None = None,
    ) -> Summary:
        del session, segments, speaker_display, user_context
        raise UnavailableSummarizationError(self._reason)
