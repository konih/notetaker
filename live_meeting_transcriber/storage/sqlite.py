from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class StorageError(RuntimeError):
    pass


def sqlite_path_from_url(database_url: str) -> Path:
    if not database_url.startswith("sqlite:"):
        raise StorageError("Only sqlite URLs are supported (expected sqlite:////path/to.db)")
    # Supported formats:
    # - sqlite:////abs/path.db
    # - sqlite:///relative.db  (rare)
    raw = database_url.removeprefix("sqlite:")
    if raw.startswith("////"):
        return Path(raw[3:])  # keep leading slash
    if raw.startswith("///"):
        return Path(raw[2:])
    if raw.startswith("//"):
        return Path(raw[2:])
    raise StorageError("Invalid sqlite URL format")


def connect(database_url: str) -> sqlite3.Connection:
    path = sqlite_path_from_url(database_url)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(r[1]) for r in rows}


def _add_column_if_missing(
    conn: sqlite3.Connection, table: str, column: str, ddl_suffix: str
) -> None:
    cols = _table_columns(conn, table)
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_suffix}")


def migrate(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS meeting_sessions (
          id TEXT PRIMARY KEY,
          title TEXT NOT NULL,
          started_at TEXT NOT NULL,
          ended_at TEXT
        )
        """
    )
    _add_column_if_missing(conn, "meeting_sessions", "notes", "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(conn, "meeting_sessions", "attendees_json", "TEXT NOT NULL DEFAULT '[]'")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS transcript_segments (
          id TEXT PRIMARY KEY,
          session_id TEXT NOT NULL,
          chunk_id TEXT,
          started_at TEXT NOT NULL,
          ended_at TEXT NOT NULL,
          text TEXT NOT NULL,
          speaker TEXT NOT NULL,
          provider TEXT,
          model TEXT,
          metadata_json TEXT,
          FOREIGN KEY(session_id) REFERENCES meeting_sessions(id)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_transcript_segments_session_id
        ON transcript_segments(session_id)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS summaries (
          id TEXT PRIMARY KEY,
          session_id TEXT NOT NULL UNIQUE,
          created_at TEXT NOT NULL,
          summary_markdown TEXT NOT NULL,
          action_items_json TEXT NOT NULL,
          decisions_json TEXT NOT NULL,
          provider TEXT,
          model TEXT,
          metadata_json TEXT,
          FOREIGN KEY(session_id) REFERENCES meeting_sessions(id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS known_people (
          id TEXT PRIMARY KEY,
          display_name TEXT NOT NULL COLLATE NOCASE,
          source TEXT NOT NULL DEFAULT 'local',
          created_at TEXT NOT NULL,
          last_used_at TEXT NOT NULL,
          UNIQUE(display_name)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_known_people_display_name
        ON known_people(display_name COLLATE NOCASE)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS session_speaker_names (
          session_id TEXT NOT NULL,
          speaker_key TEXT NOT NULL,
          display_name TEXT NOT NULL,
          PRIMARY KEY (session_id, speaker_key),
          FOREIGN KEY(session_id) REFERENCES meeting_sessions(id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS diarization_segments (
          id TEXT PRIMARY KEY,
          session_id TEXT NOT NULL,
          chunk_id TEXT,
          started_at TEXT NOT NULL,
          ended_at TEXT NOT NULL,
          speaker_key TEXT NOT NULL,
          FOREIGN KEY(session_id) REFERENCES meeting_sessions(id)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_diarization_segments_session_id
        ON diarization_segments(session_id)
        """
    )
    conn.commit()


def open_connection(database_url: str) -> sqlite3.Connection:
    conn = connect(database_url)
    migrate(conn)
    return conn


@contextmanager
def session(database_url: str) -> Iterator[sqlite3.Connection]:
    conn = open_connection(database_url)
    try:
        yield conn
    finally:
        conn.close()


def dumps_json(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def loads_json(raw: str) -> object:
    return json.loads(raw)
