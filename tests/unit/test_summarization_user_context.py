from __future__ import annotations

import asyncio
from collections.abc import Iterable
from datetime import datetime, timedelta
from pathlib import Path

from live_meeting_transcriber.application.session_service import SessionService
from live_meeting_transcriber.domain.models import (
    MeetingSession,
    Summary,
    TranscriptSegment,
)
from live_meeting_transcriber.storage.repositories import (
    SqliteMeetingSessionRepository,
    SqliteSummaryRepository,
    SqliteTranscriptRepository,
)
from live_meeting_transcriber.storage.sqlite import open_connection
from live_meeting_transcriber.summarization.service import build_summary_prompt


def test_build_summary_prompt_includes_user_context() -> None:
    session = MeetingSession(title="Sync")
    t0 = datetime.utcnow()
    segs = [
        TranscriptSegment(
            session_id=session.id,
            started_at=t0,
            ended_at=t0 + timedelta(seconds=1),
            text="Hello",
        )
    ]
    prompt = build_summary_prompt(
        session=session,
        segments=segs,
        user_context="Focus on budget decisions.",
    )
    assert "Additional context from the user" in prompt
    assert "Focus on budget decisions." in prompt


class _RecordingSummarizer:
    def __init__(self) -> None:
        self.last_user_context: str | None = "unset"

    async def summarize(
        self,
        *,
        session: MeetingSession,
        segments: Iterable[TranscriptSegment],
        speaker_display: dict[str, str] | None = None,
        user_context: str | None = None,
    ) -> Summary:
        self.last_user_context = user_context
        return Summary(session_id=session.id, summary_markdown="## Done")


def test_session_service_passes_user_context_to_summarizer(tmp_path: Path) -> None:
    conn = open_connection(f"sqlite:////{tmp_path}/t.db")
    try:
        sessions = SqliteMeetingSessionRepository(conn)
        transcripts = SqliteTranscriptRepository(conn)
        summaries = SqliteSummaryRepository(conn)
        session = sessions.create(MeetingSession(title="T"))
        t0 = datetime.utcnow()
        transcripts.append(
            TranscriptSegment(
                session_id=session.id,
                started_at=t0,
                ended_at=t0 + timedelta(seconds=1),
                text="Line one",
            )
        )
        summarizer = _RecordingSummarizer()
        svc = SessionService(
            sessions=sessions,
            transcripts=transcripts,
            summaries=summaries,
            summarizer=summarizer,
        )
        asyncio.run(
            svc.summarize_session(session_id=session.id, user_context="  emphasize risks  ")
        )
        assert summarizer.last_user_context == "emphasize risks"
        assert summaries.get_by_session(session.id) is not None
    finally:
        conn.close()
