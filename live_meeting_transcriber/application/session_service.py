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
from live_meeting_transcriber.obsidian.vault_patterns import is_placeholder_meeting_title


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

    async def summarize_session(
        self, *, session_id: UUID, user_context: str | None = None
    ) -> Summary:
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
            user_context=user_context.strip() if user_context and user_context.strip() else None,
        )
        stored = self.summaries.upsert(summary)
        self._apply_meeting_metadata_to_session(
            session_id=session_id, session=session, summary=stored
        )
        return stored

    def _apply_meeting_metadata_to_session(
        self,
        *,
        session_id: UUID,
        session: MeetingSession,
        summary: Summary,
    ) -> None:
        meta = summary.meeting_metadata
        if meta is None:
            return

        title = meta.confident_str("title")
        if title and (
            is_placeholder_meeting_title(session.title) or session.title.strip() != title
        ):
            self.sessions.update_title(session_id, title)

        participants = meta.confident_participants()
        if participants:
            merged = list(dict.fromkeys([*session.attendees, *participants]))
            if merged != session.attendees:
                self.sessions.update_details(session_id, attendees=merged)
