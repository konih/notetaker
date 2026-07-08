from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from live_meeting_transcriber.audio.backend import build_audio_capture, build_audio_device_provider
from live_meeting_transcriber.config.settings import Settings
from live_meeting_transcriber.diarization.noop import NoopDiarizationProvider
from live_meeting_transcriber.domain.ports import (
    AudioCapture,
    AudioDeviceProvider,
    DiarizationProvider,
    DiarizationRepository,
    KnownPeopleRepository,
    MeetingSessionRepository,
    SessionSpeakerNameRepository,
    SummarizationProvider,
    SummaryRepository,
    TranscriptionProvider,
    TranscriptRepository,
)
from live_meeting_transcriber.observability.logging import get_logger
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
from live_meeting_transcriber.summarization.openai_summarizer import OpenAISummarizationProvider
from live_meeting_transcriber.transcription.faster_whisper_transcriber import (
    FasterWhisperTranscriptionProvider,
)
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
    diarization_segments: DiarizationRepository
    sessions: MeetingSessionRepository
    transcripts: TranscriptRepository
    summaries: SummaryRepository
    people: KnownPeopleRepository
    session_speakers: SessionSpeakerNameRepository

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            get_logger(component="container").warning("db_connection_close_failed", exc_info=True)


def build_diarization_provider(settings: Settings) -> DiarizationProvider:
    if not settings.diarization_enabled or settings.diarization_provider.strip().lower() == "noop":
        return NoopDiarizationProvider()
    if settings.diarization_provider.strip().lower() == "pyannote":
        from live_meeting_transcriber.diarization.pyannote_provider import (
            PyannoteDiarizationProvider,
        )

        if not settings.hf_token:
            raise ProviderSelectionError(
                "HF_TOKEN is required when DIARIZATION_ENABLED=true and DIARIZATION_PROVIDER=pyannote"
            )
        return PyannoteDiarizationProvider(
            hf_token=settings.hf_token,
            model_id=settings.pyannote_model,
            pipeline_call_kw=settings.pyannote_diarization_pipeline_kwargs(),
        )
    raise ProviderSelectionError(
        f"Unsupported diarization_provider={settings.diarization_provider!r}"
    )


def build_container(settings: Settings) -> Container:
    if settings.transcription_provider == "openai" and settings.openai_api_key is None:
        raise ProviderSelectionError("OPENAI_API_KEY is required for OpenAI transcription")

    devices: AudioDeviceProvider = build_audio_device_provider(settings.audio_macos_system_capture)
    audio: AudioCapture = build_audio_capture(settings.audio_macos_system_capture)
    diarizer: DiarizationProvider = build_diarization_provider(settings)

    if settings.transcription_provider == "openai":
        transcriber: TranscriptionProvider = OpenAITranscriptionProvider(
            api_key=settings.openai_api_key or "",
            model=settings.transcription_model,
        )
    elif settings.transcription_provider == "faster_whisper":
        transcriber = FasterWhisperTranscriptionProvider(
            model_size=settings.faster_whisper_model,
            device=settings.faster_whisper_device,
            compute_type=settings.faster_whisper_compute_type,
            language=settings.faster_whisper_language,
        )
    else:
        raise ProviderSelectionError(
            f"Unsupported transcription_provider={settings.transcription_provider}"
        )

    if settings.llm_provider == "openai":
        if settings.openai_api_key:
            summarizer: SummarizationProvider = OpenAISummarizationProvider(
                api_key=settings.openai_api_key,
                model=settings.summary_model,
                vault_meetings_dir=settings.obsidian_meetings_dir,
            )
        else:
            from live_meeting_transcriber.summarization.unavailable import (
                UnavailableSummarizationProvider,
            )

            summarizer = UnavailableSummarizationProvider(
                reason="OPENAI_API_KEY is required for summaries (LLM_PROVIDER=openai)",
            )
    else:
        raise ProviderSelectionError(f"Unsupported llm_provider={settings.llm_provider}")

    conn = open_connection(settings.database_url)
    sessions: MeetingSessionRepository = SqliteMeetingSessionRepository(conn)
    transcripts: TranscriptRepository = SqliteTranscriptRepository(conn)
    summaries: SummaryRepository = SqliteSummaryRepository(conn)
    people: KnownPeopleRepository = CompositeKnownPeopleRepository(
        inner=SqliteKnownPeopleRepository(conn),
        people_dir=settings.obsidian_people_dir,
        person_template=settings.obsidian_person_template,
    )
    session_speakers: SessionSpeakerNameRepository = SqliteSessionSpeakerNameRepository(conn)
    diarization_segments: DiarizationRepository = SqliteDiarizationRepository(conn)

    return Container(
        settings=settings,
        _conn=conn,
        devices=devices,
        audio=audio,
        transcriber=transcriber,
        summarizer=summarizer,
        diarizer=diarizer,
        diarization_segments=diarization_segments,
        sessions=sessions,
        transcripts=transcripts,
        summaries=summaries,
        people=people,
        session_speakers=session_speakers,
    )
