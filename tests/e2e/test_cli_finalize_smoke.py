"""E2e smoke: finalize CLI with temp DB and mocked WhisperX."""

from __future__ import annotations

import shutil
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from live_meeting_transcriber.audio.session_recording import session_audio_dir
from live_meeting_transcriber.cli.main import app
from live_meeting_transcriber.config.settings import Settings
from live_meeting_transcriber.domain.models import MeetingSession, TranscriptSegment
from typer.testing import CliRunner

from tests.e2e.cli_helpers import build_e2e_container, patch_cli
from tests.e2e.video_helpers import patch_data_dir
from tests.fixtures.paths import MEETING_EN_WAV


def test_cli_finalize_smoke_e2e(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    patch_data_dir(monkeypatch, tmp_path)
    db = tmp_path / "finalize.sqlite3"
    settings = Settings(openai_api_key="test-key", database_url=f"sqlite:////{db}")
    container = build_e2e_container(tmp_path, settings)
    session = container.sessions.create(MeetingSession(title="Finalize Me"))
    sid: UUID = session.id
    audio_root = session_audio_dir(tmp_path, sid)
    wav = audio_root / "full_session.wav"
    if MEETING_EN_WAV.is_file():
        shutil.copy2(MEETING_EN_WAV, wav)
    else:
        wav.write_bytes(b"RIFF")

    patch_cli(monkeypatch, settings=settings, container=container)

    def fake_finalize(**kwargs):  # type: ignore[no-untyped-def]
        return [
            TranscriptSegment(
                session_id=sid,
                started_at=datetime.utcnow(),
                ended_at=datetime.utcnow() + timedelta(seconds=1),
                text="finalized segment",
                speaker="speaker_1",
            )
        ]

    monkeypatch.setattr(
        "live_meeting_transcriber.offline.whisperx_pipeline.run_whisperx_finalize",
        fake_finalize,
    )

    result = CliRunner().invoke(app, ["finalize", "--session-id", str(sid)])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "Replaced transcript with 1 segment" in result.stdout

    segments = container.transcripts.list_by_session(sid)
    assert len(segments) == 1
    assert segments[0].text == "finalized segment"
