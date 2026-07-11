"""Shared helpers for CLI e2e smoke tests (mocked recorder, temp SQLite)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from live_meeting_transcriber.application.container import Container
from live_meeting_transcriber.config.settings import Settings
from live_meeting_transcriber.domain.models import AudioChunk, TranscriptSegment
from live_meeting_transcriber.domain.ports import AudioSource, TranscriptionProvider
from live_meeting_transcriber.storage.people_composite import CompositeKnownPeopleRepository
from live_meeting_transcriber.storage.repositories import (
    SqliteDiarizationRepository,
    SqliteKnownPeopleRepository,
    SqliteMeetingSessionRepository,
    SqliteSessionSpeakerNameRepository,
    SqliteSummaryRepository,
    SqliteTranscriptRepository,
)
from live_meeting_transcriber.storage.sqlite import open_connection
from live_meeting_transcriber.utils.time import utc_now


@dataclass(frozen=True)
class FakeDevices:
    def list_sources(self) -> list[AudioSource]:
        return []

    def get_default_monitor_source(self) -> str | None:
        return "sink.monitor"

    def get_default_microphone_source(self) -> str | None:
        return "alsa_input.fake"


class FakeRecorder:
    """Stand-in for ``Recorder`` that mirrors its real persist-then-notify contract.

    The production recorder ``append``s every streamed segment to the transcript repository
    *and* calls ``on_segment`` (see ``application/recorder.py``). Capturing the injected
    ``transcripts`` repo here keeps the fake faithful so e2e tests can assert the transcript
    was actually persisted, not merely echoed to stdout.
    """

    def __init__(self, *, transcripts: object | None = None, **_kwargs: object) -> None:
        self._transcripts = transcripts

    async def record_forever(
        self,
        *,
        session_id: UUID,
        source: str,
        microphone_source: str | None = None,
        chunk_seconds: int,
        sample_rate_hz: int,
        channels: int,
        on_segment: Callable[[TranscriptSegment], object],
        **_kwargs: object,
    ) -> None:
        seg = TranscriptSegment(
            session_id=session_id,
            started_at=utc_now(),
            ended_at=utc_now() + timedelta(seconds=1),
            text="e2e smoke transcript",
        )
        if self._transcripts is not None:
            self._transcripts.append(seg)  # type: ignore[attr-defined]
        on_segment(seg)
        await asyncio.sleep(0)


@dataclass(frozen=True)
class FakeTranscriber:
    """Deterministic stand-in for the STT provider (no network, no model download).

    Default text embeds the chunk start so multi-chunk imports yield distinct segments;
    pass ``text`` for a fixed marker string.
    """

    text: str | None = None

    async def transcribe(self, *, chunk: AudioChunk) -> TranscriptSegment:
        return TranscriptSegment(
            session_id=chunk.session_id,
            chunk_id=chunk.id,
            started_at=chunk.started_at,
            ended_at=chunk.ended_at,
            text=self.text if self.text is not None else f"chunk at {chunk.started_at.isoformat()}",
        )


def build_e2e_container(
    tmp_path: Path,
    settings: Settings,
    *,
    transcriber: TranscriptionProvider | None = None,
) -> Container:
    """Real-SQLite container for CLI e2e: live repositories, fake providers.

    ``transcriber`` defaults to ``None`` (record smokes patch the Recorder instead);
    video-import e2e passes a :class:`FakeTranscriber`.
    """
    conn = open_connection(settings.database_url)
    return Container(
        settings=settings,
        _conn=conn,
        devices=FakeDevices(),
        audio=None,  # type: ignore[arg-type]
        transcriber=transcriber,  # type: ignore[arg-type]
        summarizer=None,  # type: ignore[arg-type]
        diarizer=None,  # type: ignore[arg-type]
        diarization_segments=SqliteDiarizationRepository(conn),
        sessions=SqliteMeetingSessionRepository(conn),
        transcripts=SqliteTranscriptRepository(conn),
        summaries=SqliteSummaryRepository(conn),
        people=CompositeKnownPeopleRepository(
            inner=SqliteKnownPeopleRepository(conn),
            people_dir=None,
            person_template=None,
        ),
        session_speakers=SqliteSessionSpeakerNameRepository(conn),
    )


def patch_cli(
    monkeypatch: pytest.MonkeyPatch,
    *,
    settings: Settings,
    container: Container,
) -> None:
    monkeypatch.setattr("live_meeting_transcriber.cli.main.load_settings", lambda: settings)
    monkeypatch.setattr("live_meeting_transcriber.cli.main.build_container", lambda _s: container)


def patch_fake_recorder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("live_meeting_transcriber.cli.commands.recording.Recorder", FakeRecorder)
