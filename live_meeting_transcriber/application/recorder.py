from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from live_meeting_transcriber.domain.application_events import (
    ApplicationEvent,
    AudioChunkCaptured,
    DiarizationChunkCompleted,
    RecordingFailed,
    RecordingLoopEntered,
    RecordingStopped,
    TranscriptionChunkCompleted,
    TranscriptionChunkStarted,
    TranscriptSegmentPersisted,
)
from live_meeting_transcriber.domain.models import TranscriptSegment
from live_meeting_transcriber.domain.ports import AudioCapture, DiarizationProvider, TranscriptionProvider, TranscriptRepository
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
    keep_audio_chunks: bool
    chunk_output_dir: Path

    async def record_forever(
        self,
        *,
        session_id: UUID,
        source: str,
        chunk_seconds: int,
        sample_rate_hz: int,
        channels: int,
        on_segment: Callable[[TranscriptSegment], None] | None = None,
        on_application_event: Callable[[ApplicationEvent], None] | None = None,
    ) -> None:
        log = get_logger(component="recorder", session_id=str(session_id))
        log.info("recording_started", source=source, chunk_seconds=chunk_seconds)

        self.chunk_output_dir.mkdir(parents=True, exist_ok=True)
        now = utc_now()
        _emit(
            on_application_event,
            RecordingLoopEntered(
                session_id=session_id,
                audio_source=source,
                chunk_seconds=chunk_seconds,
                at=now,
            ),
        )

        try:
            while True:
                chunk = self.audio.capture_chunk(
                    session_id=session_id,
                    source=source,
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

                log.info("transcription_started", chunk_id=str(chunk.id))
                _emit(
                    on_application_event,
                    TranscriptionChunkStarted(session_id=session_id, chunk_id=chunk.id, at=utc_now()),
                )
                segment = await self.transcriber.transcribe(chunk=chunk)
                log.info("transcription_completed", chunk_id=str(chunk.id))
                _emit(
                    on_application_event,
                    TranscriptionChunkCompleted(session_id=session_id, chunk_id=chunk.id, at=utc_now()),
                )

                # TODO: diarization provider can be enabled later.
                segment = await self.diarizer.diarize(segment=segment)
                _emit(on_application_event, DiarizationChunkCompleted(segment=segment, at=utc_now()))

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
                    except Exception:  # noqa: BLE001
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
        except Exception as e:  # noqa: BLE001
            log.exception("recording_failed")
            _emit(
                on_application_event,
                RecordingFailed(session_id=session_id, message=str(e), at=utc_now()),
            )
            raise RecorderError(str(e)) from e

