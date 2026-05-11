from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from live_meeting_transcriber.audio.capture import FfmpegPulseAudioCapture
from live_meeting_transcriber.audio.devices import PactlAudioDeviceProvider
from live_meeting_transcriber.config.settings import Settings
from live_meeting_transcriber.diarization.noop import NoopDiarizationProvider
from live_meeting_transcriber.domain.ports import (
    AudioCapture,
    AudioDeviceProvider,
    DiarizationProvider,
    MeetingSessionRepository,
    SummarizationProvider,
    SummaryRepository,
    TranscriptRepository,
    TranscriptionProvider,
)
from live_meeting_transcriber.storage.repositories import (
    SqliteMeetingSessionRepository,
    SqliteSummaryRepository,
    SqliteTranscriptRepository,
)
from live_meeting_transcriber.storage.sqlite import open_connection
from live_meeting_transcriber.summarization.openai_summarizer import OpenAISummarizationProvider
from live_meeting_transcriber.transcription.openai_transcriber import OpenAITranscriptionProvider


class ProviderSelectionError(RuntimeError):
    pass


@dataclass(frozen=True)
class Container:
    settings: Settings
    _conn: Any
    devices: AudioDeviceProvider
    audio: AudioCapture
    transcriber: TranscriptionProvider
    summarizer: SummarizationProvider
    diarizer: DiarizationProvider
    sessions: MeetingSessionRepository
    transcripts: TranscriptRepository
    summaries: SummaryRepository

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass


def build_container(settings: Settings) -> Container:
    if settings.openai_api_key is None and (
        settings.transcription_provider == "openai" or settings.llm_provider == "openai"
    ):
        raise ProviderSelectionError("OPENAI_API_KEY is required for OpenAI providers")

    devices: AudioDeviceProvider = PactlAudioDeviceProvider()
    audio: AudioCapture = FfmpegPulseAudioCapture()
    diarizer: DiarizationProvider = NoopDiarizationProvider()

    if settings.transcription_provider == "openai":
        transcriber: TranscriptionProvider = OpenAITranscriptionProvider(
            api_key=settings.openai_api_key or "",
            model=settings.transcription_model,
        )
    else:
        raise ProviderSelectionError(f"Unsupported transcription_provider={settings.transcription_provider}")

    if settings.llm_provider == "openai":
        summarizer: SummarizationProvider = OpenAISummarizationProvider(
            api_key=settings.openai_api_key or "",
            model=settings.summary_model,
        )
    else:
        raise ProviderSelectionError(f"Unsupported llm_provider={settings.llm_provider}")

    conn = open_connection(settings.database_url)
    sessions: MeetingSessionRepository = SqliteMeetingSessionRepository(conn)
    transcripts: TranscriptRepository = SqliteTranscriptRepository(conn)
    summaries: SummaryRepository = SqliteSummaryRepository(conn)

    return Container(
        settings=settings,
        _conn=conn,
        devices=devices,
        audio=audio,
        transcriber=transcriber,
        summarizer=summarizer,
        diarizer=diarizer,
        sessions=sessions,
        transcripts=transcripts,
        summaries=summaries,
    )

