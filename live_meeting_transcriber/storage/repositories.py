from __future__ import annotations

import builtins
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast
from uuid import UUID, uuid4

from live_meeting_transcriber.domain.models import (
    ActionItem,
    Decision,
    DiarizationSegment,
    MeetingMetadataProposal,
    MeetingSession,
    ProviderMetadata,
    SpeakerAlias,
    Summary,
    TranscriptSegment,
)
from live_meeting_transcriber.storage.sqlite import dumps_json, loads_json
from live_meeting_transcriber.utils.time import ensure_aware, utc_now


def _dt_to_str(dt: datetime) -> str:
    # ISO 8601 without timezone for now; application uses UTC.
    return dt.isoformat()


def _dt_from_str(raw: str) -> datetime:
    # A11: rows written before the tz-aware migration (A1) stored naive ISO strings
    # (no offset), so a DB may mix naive (old) and aware (new) rows. Coerce every read
    # to UTC-aware here — the single read boundary — so nothing downstream can hit a
    # naive/aware comparison TypeError. New rows already carry "+00:00" and are unchanged.
    return ensure_aware(datetime.fromisoformat(raw))


def _row_read(row: Any, key: str) -> Any:
    """Column access for sqlite3.Row (no ``.get()``) and other row-like mappings."""
    return row[key]


@dataclass(frozen=True)
class SqliteMeetingSessionRepository:
    conn: Any

    def create(self, session: MeetingSession) -> MeetingSession:
        self.conn.execute(
            """
            INSERT INTO meeting_sessions (id, title, started_at, ended_at, notes, attendees_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(session.id),
                session.title,
                _dt_to_str(session.started_at),
                session.ended_at and _dt_to_str(session.ended_at),
                session.notes,
                dumps_json(session.attendees),
            ),
        )
        self.conn.commit()
        return session

    def _row_to_session(self, row: Any) -> MeetingSession:
        raw_att = _row_read(row, "attendees_json") or "[]"
        attendees_raw = loads_json(raw_att) if raw_att else []
        attendees = [str(x) for x in attendees_raw] if isinstance(attendees_raw, list) else []
        notes = _row_read(row, "notes") or ""
        return MeetingSession(
            id=UUID(row["id"]),
            title=row["title"],
            started_at=_dt_from_str(row["started_at"]),
            ended_at=_dt_from_str(row["ended_at"]) if row["ended_at"] else None,
            notes=str(notes),
            attendees=attendees,
        )

    def get(self, session_id: UUID) -> MeetingSession | None:
        row = self.conn.execute(
            "SELECT id, title, started_at, ended_at, notes, attendees_json FROM meeting_sessions WHERE id = ?",
            (str(session_id),),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_session(row)

    def list(self) -> list[MeetingSession]:
        rows = self.conn.execute(
            """
            SELECT id, title, started_at, ended_at, notes, attendees_json
            FROM meeting_sessions ORDER BY started_at DESC
            """
        ).fetchall()
        return [self._row_to_session(r) for r in rows]

    def end(self, session_id: UUID) -> None:
        self.conn.execute(
            "UPDATE meeting_sessions SET ended_at = ? WHERE id = ?",
            (_dt_to_str(utc_now()), str(session_id)),
        )
        self.conn.commit()

    def reopen(self, session_id: UUID) -> MeetingSession | None:
        if self.get(session_id) is None:
            return None
        self.conn.execute(
            "UPDATE meeting_sessions SET ended_at = NULL WHERE id = ?",
            (str(session_id),),
        )
        self.conn.commit()
        return self.get(session_id)

    def update_title(self, session_id: UUID, title: str) -> MeetingSession | None:
        return self.update_details(session_id, title=title)

    def update_details(
        self,
        session_id: UUID,
        *,
        title: str | None = None,
        notes: str | None = None,
        attendees: builtins.list[str] | None = None,
    ) -> MeetingSession | None:
        cur_session = self.get(session_id)
        if cur_session is None:
            return None
        new_title = title if title is not None else cur_session.title
        new_notes = notes if notes is not None else cur_session.notes
        new_attendees = attendees if attendees is not None else cur_session.attendees
        cur = self.conn.execute(
            """
            UPDATE meeting_sessions
            SET title = ?, notes = ?, attendees_json = ?
            WHERE id = ?
            """,
            (new_title, new_notes, dumps_json(new_attendees), str(session_id)),
        )
        self.conn.commit()
        if cur.rowcount == 0:
            return None
        return self.get(session_id)

    def delete(self, session_id: UUID) -> bool:
        sid = str(session_id)
        row = self.conn.execute(
            "SELECT 1 FROM meeting_sessions WHERE id = ?",
            (sid,),
        ).fetchone()
        if row is None:
            return False
        self.conn.execute("DELETE FROM transcript_segments WHERE session_id = ?", (sid,))
        self.conn.execute("DELETE FROM summaries WHERE session_id = ?", (sid,))
        self.conn.execute("DELETE FROM session_speaker_names WHERE session_id = ?", (sid,))
        self.conn.execute("DELETE FROM diarization_segments WHERE session_id = ?", (sid,))
        self.conn.execute("DELETE FROM meeting_sessions WHERE id = ?", (sid,))
        self.conn.commit()
        return True


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
                segment.speaker,
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
                    speaker=str(r["speaker"]),
                    metadata=metadata,
                )
            )
        return segments

    def replace_session_transcript(
        self, session_id: UUID, segments: list[TranscriptSegment]
    ) -> None:
        sid = str(session_id)
        self.conn.execute("DELETE FROM transcript_segments WHERE session_id = ?", (sid,))
        for segment in segments:
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
                    segment.speaker,
                    provider,
                    model,
                    metadata_json,
                ),
            )
        self.conn.commit()

    def update_segment_text(self, segment_id: UUID, text: str) -> TranscriptSegment | None:
        t = text.strip()
        if not t:
            return None
        row = self.conn.execute(
            """
            SELECT id, session_id, chunk_id, started_at, ended_at, text, speaker, provider, model, metadata_json
            FROM transcript_segments WHERE id = ?
            """,
            (str(segment_id),),
        ).fetchone()
        if row is None:
            return None
        self.conn.execute(
            "UPDATE transcript_segments SET text = ? WHERE id = ?",
            (t, str(segment_id)),
        )
        self.conn.commit()
        metadata: ProviderMetadata | None = None
        if row["provider"] and row["model"]:
            extra = loads_json(row["metadata_json"]) if row["metadata_json"] else {}
            metadata = ProviderMetadata(provider=row["provider"], model=row["model"], extra=extra)  # type: ignore[arg-type]
        return TranscriptSegment(
            id=UUID(row["id"]),
            session_id=UUID(row["session_id"]),
            chunk_id=UUID(row["chunk_id"]) if row["chunk_id"] else None,
            started_at=_dt_from_str(row["started_at"]),
            ended_at=_dt_from_str(row["ended_at"]),
            text=t,
            speaker=str(row["speaker"]),
            metadata=metadata,
        )

    def update_segment_speaker(self, segment_id: UUID, speaker: str) -> TranscriptSegment | None:
        spk = speaker.strip()
        if not spk:
            return None
        row = self.conn.execute(
            """
            SELECT id, session_id, chunk_id, started_at, ended_at, text, speaker, provider, model, metadata_json
            FROM transcript_segments WHERE id = ?
            """,
            (str(segment_id),),
        ).fetchone()
        if row is None:
            return None
        self.conn.execute(
            "UPDATE transcript_segments SET speaker = ? WHERE id = ?",
            (spk, str(segment_id)),
        )
        self.conn.commit()
        metadata: ProviderMetadata | None = None
        if row["provider"] and row["model"]:
            extra = loads_json(row["metadata_json"]) if row["metadata_json"] else {}
            metadata = ProviderMetadata(provider=row["provider"], model=row["model"], extra=extra)  # type: ignore[arg-type]
        return TranscriptSegment(
            id=UUID(row["id"]),
            session_id=UUID(row["session_id"]),
            chunk_id=UUID(row["chunk_id"]) if row["chunk_id"] else None,
            started_at=_dt_from_str(row["started_at"]),
            ended_at=_dt_from_str(row["ended_at"]),
            text=str(row["text"]),
            speaker=spk,
            metadata=metadata,
        )


@dataclass(frozen=True)
class SqliteKnownPeopleRepository:
    """Persistent people list for TUI autocomplete (``source`` reserved for future Obsidian vault sync)."""

    conn: Any

    def list_for_autocomplete(self) -> list[str]:
        rows = self.conn.execute(
            """
            SELECT display_name FROM known_people
            ORDER BY last_used_at DESC, display_name COLLATE NOCASE ASC
            """
        ).fetchall()
        return [str(r["display_name"]) for r in rows]

    def search_prefix(self, prefix: str, *, limit: int = 25) -> list[str]:
        p = prefix.strip()
        if not p:
            return self.list_for_autocomplete()[:limit]
        rows = self.conn.execute(
            """
            SELECT display_name FROM known_people
            WHERE display_name LIKE ? ESCAPE '\\'
            ORDER BY last_used_at DESC, display_name COLLATE NOCASE ASC
            LIMIT ?
            """,
            (f"{p}%", limit),
        ).fetchall()
        return [str(r["display_name"]) for r in rows]

    def touch(self, display_name: str) -> None:
        name = display_name.strip()
        if not name:
            return
        now = _dt_to_str(utc_now())
        pid = str(uuid4())
        self.conn.execute(
            """
            INSERT INTO known_people (id, display_name, source, created_at, last_used_at)
            VALUES (?, ?, 'local', ?, ?)
            ON CONFLICT(display_name) DO UPDATE SET last_used_at=excluded.last_used_at
            """,
            (pid, name, now, now),
        )
        self.conn.commit()


@dataclass(frozen=True)
class SqliteSessionSpeakerNameRepository:
    conn: Any

    def get_map(self, session_id: UUID) -> dict[str, str]:
        rows = self.conn.execute(
            """
            SELECT speaker_key, display_name FROM session_speaker_names
            WHERE session_id = ?
            """,
            (str(session_id),),
        ).fetchall()
        return {str(r["speaker_key"]): str(r["display_name"]) for r in rows}

    def replace_map(self, session_id: UUID, mapping: dict[str, str]) -> None:
        sid = str(session_id)
        self.conn.execute("DELETE FROM session_speaker_names WHERE session_id = ?", (sid,))
        for key, raw in mapping.items():
            val = raw.strip()
            if not val:
                continue
            self.conn.execute(
                """
                INSERT INTO session_speaker_names (session_id, speaker_key, display_name)
                VALUES (?, ?, ?)
                """,
                (sid, key, val),
            )
        self.conn.commit()

    def set_alias(self, session_id: UUID, speaker_key: str, display_name: str) -> None:
        sid = str(session_id)
        key = speaker_key.strip()
        name = display_name.strip()
        if not key or not name:
            return
        self.conn.execute(
            """
            INSERT INTO session_speaker_names (session_id, speaker_key, display_name)
            VALUES (?, ?, ?)
            ON CONFLICT(session_id, speaker_key) DO UPDATE SET display_name=excluded.display_name
            """,
            (sid, key, name),
        )
        self.conn.commit()

    def list_aliases(self, session_id: UUID) -> list[SpeakerAlias]:
        rows = self.conn.execute(
            """
            SELECT speaker_key, display_name FROM session_speaker_names
            WHERE session_id = ?
            ORDER BY speaker_key COLLATE NOCASE
            """,
            (str(session_id),),
        ).fetchall()
        return [
            SpeakerAlias(
                session_id=session_id,
                speaker_key=str(r["speaker_key"]),
                display_name=str(r["display_name"]),
            )
            for r in rows
        ]


@dataclass(frozen=True)
class SqliteDiarizationRepository:
    conn: Any

    def delete_for_session(self, session_id: UUID) -> None:
        self.conn.execute(
            "DELETE FROM diarization_segments WHERE session_id = ?", (str(session_id),)
        )
        self.conn.commit()

    def replace_for_session(self, session_id: UUID, segments: list[DiarizationSegment]) -> None:
        self.delete_for_session(session_id)
        self.append_segments(session_id, segments)

    def append_segments(self, session_id: UUID, segments: list[DiarizationSegment]) -> None:
        if not segments:
            return
        sid = str(session_id)
        for seg in segments:
            self.conn.execute(
                """
                INSERT INTO diarization_segments (id, session_id, chunk_id, started_at, ended_at, speaker_key)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid4()),
                    sid,
                    str(seg.chunk_id) if seg.chunk_id else None,
                    _dt_to_str(seg.started_at),
                    _dt_to_str(seg.ended_at),
                    seg.speaker_key,
                ),
            )
        self.conn.commit()

    def list_by_session(self, session_id: UUID) -> list[DiarizationSegment]:
        rows = self.conn.execute(
            """
            SELECT chunk_id, started_at, ended_at, speaker_key
            FROM diarization_segments
            WHERE session_id = ?
            ORDER BY started_at ASC
            """,
            (str(session_id),),
        ).fetchall()
        out: list[DiarizationSegment] = []
        for r in rows:
            out.append(
                DiarizationSegment(
                    started_at=_dt_from_str(r["started_at"]),
                    ended_at=_dt_from_str(r["ended_at"]),
                    speaker_key=str(r["speaker_key"]),
                    chunk_id=UUID(str(r["chunk_id"])) if r["chunk_id"] else None,
                )
            )
        return out


@dataclass(frozen=True)
class SqliteSummaryRepository:
    conn: Any

    def upsert(self, summary: Summary) -> Summary:
        provider = summary.metadata.provider if summary.metadata else None
        model = summary.metadata.model if summary.metadata else None
        extra: dict[str, object] = dict(summary.metadata.extra) if summary.metadata else {}
        if summary.meeting_metadata is not None:
            extra["meeting_metadata"] = summary.meeting_metadata.model_dump(mode="json")
        metadata_json = dumps_json(extra) if summary.metadata or summary.meeting_metadata else None

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
        meeting_metadata = None
        if row["provider"] and row["model"]:
            extra: dict[str, Any] = (
                cast("dict[str, Any]", loads_json(row["metadata_json"]))
                if row["metadata_json"]
                else {}
            )
            raw_meta = extra.pop("meeting_metadata", None)
            if isinstance(raw_meta, dict):
                meeting_metadata = MeetingMetadataProposal.model_validate(raw_meta)
            metadata = ProviderMetadata(provider=row["provider"], model=row["model"], extra=extra)

        action_items = [
            ActionItem(**ai)
            for ai in cast("list[dict[str, Any]]", loads_json(row["action_items_json"]))
        ]
        decisions = [
            Decision(**d) for d in cast("list[dict[str, Any]]", loads_json(row["decisions_json"]))
        ]

        return Summary(
            id=UUID(row["id"]),
            session_id=UUID(row["session_id"]),
            created_at=_dt_from_str(row["created_at"]),
            summary_markdown=row["summary_markdown"],
            action_items=action_items,
            decisions=decisions,
            meeting_metadata=meeting_metadata,
            metadata=metadata,
        )
