from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path

from live_meeting_transcriber.application.session_service import SessionService
from live_meeting_transcriber.domain.models import (
    MeetingMetadataProposal,
    MeetingSession,
    Summary,
    TranscriptSegment,
)
from live_meeting_transcriber.domain.ports import (
    MeetingSessionRepository,
    SummaryRepository,
    TranscriptRepository,
)
from live_meeting_transcriber.storage.repositories import (
    SqliteMeetingSessionRepository,
    SqliteSummaryRepository,
    SqliteTranscriptRepository,
)
from live_meeting_transcriber.storage.sqlite import open_connection


class _FakeSummarizer:
    async def summarize(self, **kwargs: object) -> Summary:
        session = kwargs["session"]
        assert isinstance(session, MeetingSession)
        return Summary(
            session_id=session.id,
            summary_markdown="## Summary\n- Done",
            meeting_metadata=MeetingMetadataProposal(
                title="REWE Tech Platform Review",
                confidence={"title": True},
            ),
        )


def test_summarize_applies_confident_title(tmp_path: Path) -> None:
    conn = open_connection(f"sqlite:////{tmp_path}/db.sqlite3")
    try:
        sessions: MeetingSessionRepository = SqliteMeetingSessionRepository(conn)
        transcripts: TranscriptRepository = SqliteTranscriptRepository(conn)
        summaries: SummaryRepository = SqliteSummaryRepository(conn)
        session = sessions.create(MeetingSession(title="Meeting 2026-06-03T11:03:27"))
        transcripts.append(
            TranscriptSegment(
                session_id=session.id,
                started_at=session.started_at,
                ended_at=session.started_at + timedelta(seconds=1),
                text="Platform review discussion",
            )
        )
        svc = SessionService(
            sessions=sessions,
            transcripts=transcripts,
            summaries=summaries,
            summarizer=_FakeSummarizer(),
        )
        asyncio.run(svc.summarize_session(session_id=session.id))
        updated = sessions.get(session.id)
        assert updated is not None
        assert updated.title == "REWE Tech Platform Review"
    finally:
        conn.close()
