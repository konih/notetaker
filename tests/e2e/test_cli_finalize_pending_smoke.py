"""E2e smoke: `finalize-pending` backfill CLI, mocked WhisperX.

Answers "is diarization working" the way the app itself failed to: it
finds sessions whose auto-finalize-on-stop never actually completed
(all segments still "unknown") and re-runs finalize for each of them.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from live_meeting_transcriber.application.container import Container
from live_meeting_transcriber.audio.session_recording import session_audio_dir
from live_meeting_transcriber.cli.main import app
from live_meeting_transcriber.config.settings import Settings
from live_meeting_transcriber.domain.models import MeetingSession, TranscriptSegment
from typer.testing import CliRunner

from tests.e2e.cli_helpers import build_e2e_container, patch_cli
from tests.e2e.video_helpers import patch_data_dir


def _seed_session(
    container: Container, *, title: str, ended: bool, speaker: str, tmp_path: Path
) -> UUID:
    session = container.sessions.create(MeetingSession(title=title))
    sid: UUID = session.id
    if ended:
        container.sessions.end(sid)
    audio_root = session_audio_dir(tmp_path, sid)
    (audio_root / "full_session.wav").parent.mkdir(parents=True, exist_ok=True)
    (audio_root / "full_session.wav").write_bytes(b"RIFF")
    container.transcripts.append(
        TranscriptSegment(
            session_id=sid,
            started_at=datetime.now(UTC),
            ended_at=datetime.now(UTC) + timedelta(seconds=1),
            text="never finalized",
            speaker=speaker,
        )
    )
    return sid


def test_finalize_pending_backfills_only_all_unknown_ended_sessions(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    patch_data_dir(monkeypatch, tmp_path)
    db = tmp_path / "finalize_pending.sqlite3"
    settings = Settings(openai_api_key="test-key", database_url=f"sqlite:////{db}")
    container = build_e2e_container(tmp_path, settings)

    dropped_sid = _seed_session(
        container, title="Dropped on exit", ended=True, speaker="unknown", tmp_path=tmp_path
    )
    already_done_sid = _seed_session(
        container, title="Already diarized", ended=True, speaker="speaker_1", tmp_path=tmp_path
    )
    still_recording_sid = _seed_session(
        container, title="Still recording", ended=False, speaker="unknown", tmp_path=tmp_path
    )

    patch_cli(monkeypatch, settings=settings, container=container)

    finalized_ids: list[UUID] = []

    def fake_finalize(*, session_id: UUID, **kwargs: object) -> list[TranscriptSegment]:
        finalized_ids.append(session_id)
        return [
            TranscriptSegment(
                session_id=session_id,
                started_at=datetime.now(UTC),
                ended_at=datetime.now(UTC) + timedelta(seconds=1),
                text="finalized segment",
                speaker="speaker_1",
            )
        ]

    monkeypatch.setattr(
        "live_meeting_transcriber.offline.whisperx_pipeline.run_whisperx_finalize",
        fake_finalize,
    )

    result = CliRunner().invoke(app, ["finalize-pending"])
    assert result.exit_code == 0, result.stdout + result.stderr

    assert finalized_ids == [dropped_sid]
    assert str(dropped_sid) in result.stdout
    assert str(already_done_sid) not in result.stdout
    assert str(still_recording_sid) not in result.stdout

    segments = container.transcripts.list_by_session(dropped_sid)
    assert [s.speaker for s in segments] == ["speaker_1"]


def test_finalize_pending_dry_run_lists_without_running(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    patch_data_dir(monkeypatch, tmp_path)
    db = tmp_path / "finalize_pending_dry.sqlite3"
    settings = Settings(openai_api_key="test-key", database_url=f"sqlite:////{db}")
    container = build_e2e_container(tmp_path, settings)
    dropped_sid = _seed_session(
        container, title="Dropped on exit", ended=True, speaker="unknown", tmp_path=tmp_path
    )
    patch_cli(monkeypatch, settings=settings, container=container)

    called = False

    def fake_finalize(**kwargs: object) -> list[TranscriptSegment]:
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(
        "live_meeting_transcriber.offline.whisperx_pipeline.run_whisperx_finalize",
        fake_finalize,
    )

    result = CliRunner().invoke(app, ["finalize-pending", "--dry-run"])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert not called
    assert str(dropped_sid) in result.stdout

    segments = container.transcripts.list_by_session(dropped_sid)
    assert [s.speaker for s in segments] == ["unknown"]
