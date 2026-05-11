from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from live_meeting_transcriber.domain.models import (
    ActionItem,
    Decision,
    MeetingSession,
    ProviderMetadata,
    Summary,
    TranscriptSegment,
)
from live_meeting_transcriber.storage.sqlite import dumps_json, loads_json


def _dt_to_str(dt: datetime) -> str:
    # ISO 8601 without timezone for now; application uses UTC.
    return dt.isoformat()


def _dt_from_str(raw: str) -> datetime:
    return datetime.fromisoformat(raw)


@dataclass(frozen=True)
class SqliteMeetingSessionRepository:
    conn: Any

    def create(self, session: MeetingSession) -> MeetingSession:
        self.conn.execute(
            "INSERT INTO meeting_sessions (id, title, started_at, ended_at) VALUES (?, ?, ?, ?)",
            (str(session.id), session.title, _dt_to_str(session.started_at), session.ended_at and _dt_to_str(session.ended_at)),
        )
        self.conn.commit()
        return session

    def get(self, session_id: UUID) -> MeetingSession | None:
        row = self.conn.execute(
            "SELECT id, title, started_at, ended_at FROM meeting_sessions WHERE id = ?",
            (str(session_id),),
        ).fetchone()
        if row is None:
            return None
        return MeetingSession(
            id=UUID(row["id"]),
            title=row["title"],
            started_at=_dt_from_str(row["started_at"]),
            ended_at=_dt_from_str(row["ended_at"]) if row["ended_at"] else None,
        )

    def list(self) -> list[MeetingSession]:
        rows = self.conn.execute(
            "SELECT id, title, started_at, ended_at FROM meeting_sessions ORDER BY started_at DESC"
        ).fetchall()
        return [
            MeetingSession(
                id=UUID(r["id"]),
                title=r["title"],
                started_at=_dt_from_str(r["started_at"]),
                ended_at=_dt_from_str(r["ended_at"]) if r["ended_at"] else None,
            )
            for r in rows
        ]

    def end(self, session_id: UUID) -> None:
        self.conn.execute(
            "UPDATE meeting_sessions SET ended_at = ? WHERE id = ?",
            (_dt_to_str(datetime.utcnow()), str(session_id)),
        )
        self.conn.commit()

    def update_title(self, session_id: UUID, title: str) -> MeetingSession | None:
        cur = self.conn.execute(
            "UPDATE meeting_sessions SET title = ? WHERE id = ?",
            (title, str(session_id)),
        )
        self.conn.commit()
        if cur.rowcount == 0:
            return None
        return self.get(session_id)


@dataclass(frozen=True)
class SqliteTranscriptRepository:
    conn: Any

    def append(self, segment: TranscriptSegment) -> TranscriptSegment:
        provider = segment.metadata.provider if segment.metadata else None
        model = segment.metadata.model if segment.metadata else None
        metadata_json = dumps_json(segment.metadata.extra) if segment.metadata else None

        self.conn.execute(
            """
            INSERT INTO transcript_segments
              (id, session_id, chunk_id, started_at, ended_at, text, speaker, provider, model, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(segment.id),
                str(segment.session_id),
                str(segment.chunk_id) if segment.chunk_id else None,
                _dt_to_str(segment.started_at),
                _dt_to_str(segment.ended_at),
                segment.text,
                segment.speaker.value,
                provider,
                model,
                metadata_json,
            ),
        )
        self.conn.commit()
        return segment

    def list_by_session(self, session_id: UUID) -> list[TranscriptSegment]:
        rows = self.conn.execute(
            """
            SELECT id, session_id, chunk_id, started_at, ended_at, text, speaker, provider, model, metadata_json
            FROM transcript_segments
            WHERE session_id = ?
            ORDER BY started_at ASC
            """,
            (str(session_id),),
        ).fetchall()

        segments: list[TranscriptSegment] = []
        for r in rows:
            metadata: ProviderMetadata | None = None
            if r["provider"] and r["model"]:
                extra = loads_json(r["metadata_json"]) if r["metadata_json"] else {}
                metadata = ProviderMetadata(provider=r["provider"], model=r["model"], extra=extra)  # type: ignore[arg-type]

            segments.append(
                TranscriptSegment(
                    id=UUID(r["id"]),
                    session_id=UUID(r["session_id"]),
                    chunk_id=UUID(r["chunk_id"]) if r["chunk_id"] else None,
                    started_at=_dt_from_str(r["started_at"]),
                    ended_at=_dt_from_str(r["ended_at"]),
                    text=r["text"],
                    speaker=r["speaker"],
                    metadata=metadata,
                )
            )
        return segments


@dataclass(frozen=True)
class SqliteSummaryRepository:
    conn: Any

    def upsert(self, summary: Summary) -> Summary:
        provider = summary.metadata.provider if summary.metadata else None
        model = summary.metadata.model if summary.metadata else None
        metadata_json = dumps_json(summary.metadata.extra) if summary.metadata else None

        action_items_json = dumps_json([ai.model_dump(mode="json") for ai in summary.action_items])
        decisions_json = dumps_json([d.model_dump(mode="json") for d in summary.decisions])

        self.conn.execute(
            """
            INSERT INTO summaries
              (id, session_id, created_at, summary_markdown, action_items_json, decisions_json, provider, model, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
              id=excluded.id,
              created_at=excluded.created_at,
              summary_markdown=excluded.summary_markdown,
              action_items_json=excluded.action_items_json,
              decisions_json=excluded.decisions_json,
              provider=excluded.provider,
              model=excluded.model,
              metadata_json=excluded.metadata_json
            """,
            (
                str(summary.id),
                str(summary.session_id),
                _dt_to_str(summary.created_at),
                summary.summary_markdown,
                action_items_json,
                decisions_json,
                provider,
                model,
                metadata_json,
            ),
        )
        self.conn.commit()
        return summary

    def get_by_session(self, session_id: UUID) -> Summary | None:
        row = self.conn.execute(
            """
            SELECT id, session_id, created_at, summary_markdown, action_items_json, decisions_json, provider, model, metadata_json
            FROM summaries
            WHERE session_id = ?
            """,
            (str(session_id),),
        ).fetchone()
        if row is None:
            return None

        metadata: ProviderMetadata | None = None
        if row["provider"] and row["model"]:
            extra = loads_json(row["metadata_json"]) if row["metadata_json"] else {}
            metadata = ProviderMetadata(provider=row["provider"], model=row["model"], extra=extra)  # type: ignore[arg-type]

        action_items = [ActionItem(**ai) for ai in loads_json(row["action_items_json"])]  # type: ignore[arg-type]
        decisions = [Decision(**d) for d in loads_json(row["decisions_json"])]  # type: ignore[arg-type]

        return Summary(
            id=UUID(row["id"]),
            session_id=UUID(row["session_id"]),
            created_at=_dt_from_str(row["created_at"]),
            summary_markdown=row["summary_markdown"],
            action_items=action_items,
            decisions=decisions,
            metadata=metadata,
        )
