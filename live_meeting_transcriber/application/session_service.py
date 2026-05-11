from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from live_meeting_transcriber.domain.models import MeetingSession, Summary
from live_meeting_transcriber.domain.ports import (
    MeetingSessionRepository,
    SummarizationProvider,
    SummaryRepository,
    TranscriptRepository,
)


@dataclass(frozen=True)
class SessionService:
    sessions: MeetingSessionRepository
    transcripts: TranscriptRepository
    summaries: SummaryRepository
    summarizer: SummarizationProvider

    def create_session(self, *, title: str) -> MeetingSession:
        session = MeetingSession(title=title)
        return self.sessions.create(session)

    def list_sessions(self) -> list[MeetingSession]:
        return self.sessions.list()

    def get_session(self, session_id: UUID) -> MeetingSession:
        session = self.sessions.get(session_id)
        if session is None:
            raise KeyError(f"Unknown session_id={session_id}")
        return session

    async def summarize_session(self, *, session_id: UUID) -> Summary:
        session = self.get_session(session_id)
        segments = self.transcripts.list_by_session(session_id)
        summary = await self.summarizer.summarize(session=session, segments=segments)
        return self.summaries.upsert(summary)

