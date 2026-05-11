from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from live_meeting_transcriber.audio.wav_level import peak_linear_from_wav_path
from live_meeting_transcriber.diarization.merge_service import merge_diarization_into_transcript_segment
from live_meeting_transcriber.domain.application_events import (
    ApplicationEvent,
    AudioChunkCaptured,
    AudioChunkLevelMeasured,
    DiarizationChunkCompleted,
    DiarizationFailed,
    RecordingFailed,
    RecordingLoopEntered,
    RecordingStopped,
    TranscriptionChunkCompleted,
    TranscriptionChunkEmpty,
    TranscriptionChunkStarted,
    TranscriptSegmentPersisted,
)
from live_meeting_transcriber.domain.exceptions import EmptyTranscriptionError
from live_meeting_transcriber.domain.models import DiarizationSegment, TranscriptSegment
from live_meeting_transcriber.domain.ports import (
    AudioCapture,
    DiarizationProvider,
    DiarizationRepository,
    TranscriptionProvider,
    TranscriptRepository,
)
from live_meeting_transcriber.observability.logging import get_logger
from live_meeting_transcriber.utils.time import utc_now


class RecorderError(RuntimeError):
    pass


def _emit(
    sink: Callable[[ApplicationEvent], None] | None,
    event: ApplicationEvent,
) -> None:
    if sink is None:
        return
    sink(event)


@dataclass(frozen=True)
class Recorder:
    audio: AudioCapture
    transcriber: TranscriptionProvider
    diarizer: DiarizationProvider
    transcripts: TranscriptRepository
    diarization_segments: DiarizationRepository
    keep_audio_chunks: bool
    chunk_output_dir: Path
    diarization_enabled: bool = False

    async def record_forever(
        self,
        *,
        session_id: UUID,
        source: str,
        microphone_source: str | None = None,
        chunk_seconds: int,
        sample_rate_hz: int,
        channels: int,
        on_segment: Callable[[TranscriptSegment], None] | None = None,
        on_application_event: Callable[[ApplicationEvent], None] | None = None,
    ) -> None:
        log = get_logger(component="recorder", session_id=str(session_id))
        log.info(
            "recording_started",
            source=source,
            microphone_source=microphone_source,
            chunk_seconds=chunk_seconds,
        )

        self.chunk_output_dir.mkdir(parents=True, exist_ok=True)
        now = utc_now()
        _emit(
            on_application_event,
            RecordingLoopEntered(
                session_id=session_id,
                audio_source=source,
                chunk_seconds=chunk_seconds,
                microphone_source=microphone_source,
                at=now,
            ),
        )

        try:
            while True:
                chunk = await asyncio.to_thread(
                    self.audio.capture_chunk,
                    session_id=session_id,
                    source=source,
                    microphone_source=microphone_source,
                    chunk_seconds=chunk_seconds,
                    sample_rate_hz=sample_rate_hz,
                    channels=channels,
                    output_dir=self.chunk_output_dir,
                )
                log.info("audio_chunk_captured", chunk_id=str(chunk.id), path=str(chunk.path))
                _emit(
                    on_application_event,
                    AudioChunkCaptured(session_id=session_id, chunk_id=chunk.id, at=utc_now()),
                )
                try:
                    peak = peak_linear_from_wav_path(chunk.path)
                except Exception:
                    peak = 0.0
                _emit(
                    on_application_event,
                    AudioChunkLevelMeasured(
                        session_id=session_id,
                        chunk_id=chunk.id,
                        peak_linear=peak,
                        at=utc_now(),
                    ),
                )

                log.info("transcription_started", chunk_id=str(chunk.id))
                _emit(
                    on_application_event,
                    TranscriptionChunkStarted(session_id=session_id, chunk_id=chunk.id, at=utc_now()),
                )
                try:
                    segment = await self.transcriber.transcribe(chunk=chunk)
                except EmptyTranscriptionError:
                    log.warning("transcription_empty_chunk", chunk_id=str(chunk.id))
                    _emit(
                        on_application_event,
                        TranscriptionChunkEmpty(
                            session_id=session_id,
                            chunk_id=chunk.id,
                            at=utc_now(),
                        ),
                    )
                    if not self.keep_audio_chunks:
                        try:
                            chunk.path.unlink(missing_ok=True)
                        except Exception:
                            log.warning("audio_chunk_cleanup_failed", path=str(chunk.path))
                    await asyncio.sleep(0)
                    continue

                log.info("transcription_completed", chunk_id=str(chunk.id))
                _emit(
                    on_application_event,
                    TranscriptionChunkCompleted(session_id=session_id, chunk_id=chunk.id, at=utc_now()),
                )

                diar_segments: list[DiarizationSegment] = []
                if self.diarization_enabled:
                    try:
                        diar_segments = await self.diarizer.diarize_chunk(chunk=chunk)
                    except Exception as e:  # noqa: BLE001
                        log.warning("diarization_failed", chunk_id=str(chunk.id), error=str(e))
                        _emit(
                            on_application_event,
                            DiarizationFailed(
                                session_id=session_id,
                                chunk_id=chunk.id,
                                message=str(e),
                                at=utc_now(),
                            ),
                        )
                segment = merge_diarization_into_transcript_segment(segment, diar_segments)
                if self.diarization_enabled and diar_segments:
                    self.diarization_segments.append_segments(session_id, diar_segments)
                detected = frozenset({segment.speaker} | {d.speaker_key for d in diar_segments})
                _emit(
                    on_application_event,
                    DiarizationChunkCompleted(
                        segment=segment,
                        detected_speakers=detected,
                        at=utc_now(),
                    ),
                )

                self.transcripts.append(segment)
                log.info("transcript_segment_saved", segment_id=str(segment.id))
                _emit(
                    on_application_event,
                    TranscriptSegmentPersisted(segment=segment, at=utc_now()),
                )

                if on_segment is not None:
                    on_segment(segment)

                if not self.keep_audio_chunks:
                    try:
                        chunk.path.unlink(missing_ok=True)
                    except Exception:
                        log.warning("audio_chunk_cleanup_failed", path=str(chunk.path))

                await asyncio.sleep(0)  # allow cancellation
        except asyncio.CancelledError:
            log.info("recording_cancelled")
            _emit(
                on_application_event,
                RecordingStopped(session_id=session_id, at=utc_now()),
            )
            raise
        except KeyboardInterrupt:
            log.info("recording_interrupted")
            raise
        except Exception as e:
            log.exception("recording_failed")
            _emit(
                on_application_event,
                RecordingFailed(session_id=session_id, message=str(e), at=utc_now()),
            )
            raise RecorderError(str(e)) from e

