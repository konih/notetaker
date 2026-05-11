from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from live_meeting_transcriber.domain.models import MeetingSession, Summary
from live_meeting_transcriber.domain.ports import (
    MeetingSessionRepository,
    SessionSpeakerNameRepository,
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
    session_speakers: SessionSpeakerNameRepository | None = None

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
        speaker_display: dict[str, str] | None = None
        if self.session_speakers is not None:
            m = self.session_speakers.get_map(session_id)
            speaker_display = m if m else None
        summary = await self.summarizer.summarize(
            session=session,
            segments=segments,
            speaker_display=speaker_display,
        )
        return self.summaries.upsert(summary)
