from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from live_meeting_transcriber.application.session_media import (
    collect_session_media,
    format_session_media_inventory,
)


def test_collect_session_media_lists_existing_files_only(tmp_path: Path) -> None:
    sid = uuid4()
    sid_s = str(sid)
    chunks = tmp_path / "chunks" / sid_s
    chunks.mkdir(parents=True)
    (chunks / "0001.wav").write_bytes(b"x" * 100)
    sessions = tmp_path / "sessions" / sid_s
    sessions.mkdir(parents=True)
    (sessions / "full_session.wav").write_bytes(b"y" * 200)

    inv = collect_session_media(tmp_path, sid)
    assert len(inv.chunk_wavs) == 1
    assert inv.chunk_wavs[0].size_bytes == 100
    assert inv.full_session_wav is not None
    assert inv.full_session_wav.size_bytes == 200
    assert inv.has_any

    text = format_session_media_inventory(inv)
    assert "Chunk WAVs" in text
    assert "full_session.wav" in text


def test_collect_session_media_empty_when_missing(tmp_path: Path) -> None:
    sid = uuid4()
    inv = collect_session_media(tmp_path, sid)
    assert not inv.has_any
    assert "No media files" in format_session_media_inventory(inv)
