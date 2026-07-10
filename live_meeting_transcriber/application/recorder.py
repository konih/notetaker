from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from live_meeting_transcriber.application.dual_path import transcriber_supports_dual_path
from live_meeting_transcriber.audio.session_recording import (
    append_chunk_with_timeline,
    session_audio_dir,
)
from live_meeting_transcriber.audio.stereo import extract_mono_channel_wav, rms_mixdown_to_mono_wav
from live_meeting_transcriber.audio.wav_level import peak_linear_from_wav_path
from live_meeting_transcriber.domain.application_events import (
    ApplicationEvent,
    AudioChunkCaptured,
    AudioChunkLevelMeasured,
    DiarizationChunkCompleted,
    RecordingFailed,
    RecordingLoopEntered,
    RecordingStopped,
    TranscriptionChunkCompleted,
    TranscriptionChunkEmpty,
    TranscriptionChunkFailed,
    TranscriptionChunkStarted,
    TranscriptionUnavailable,
    TranscriptSegmentPersisted,
)
from live_meeting_transcriber.domain.exceptions import (
    EmptyTranscriptionError,
    TranscriptionProviderError,
)
from live_meeting_transcriber.domain.models import AudioChunk, TranscriptSegment
from live_meeting_transcriber.domain.ports import (
    AudioCapture,
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
    transcripts: TranscriptRepository
    keep_audio_chunks: bool
    chunk_output_dir: Path
    data_dir: Path
    audio_stereo_mode: str
    transcription_provider: str

    async def _skip_transcription_chunk(
        self,
        *,
        chunk: AudioChunk,
        on_application_event: Callable[[ApplicationEvent], None] | None,
        event: TranscriptionChunkEmpty | TranscriptionChunkFailed,
        log: Any,
    ) -> None:
        _emit(on_application_event, event)
        if not self.keep_audio_chunks:
            try:
                chunk.path.unlink(missing_ok=True)
            except OSError:
                log.warning("audio_chunk_cleanup_failed", path=str(chunk.path))
        await asyncio.sleep(0)

    def _discard_chunk_audio(self, chunk: AudioChunk, log: Any) -> None:
        """Remove the per-chunk WAV once its audio has been folded into the session
        WAV (and transcribed), unless the operator asked to keep chunks."""
        if not self.keep_audio_chunks:
            try:
                chunk.path.unlink(missing_ok=True)
            except OSError:
                log.warning("audio_chunk_cleanup_failed", path=str(chunk.path))

    async def _ingest_captured_chunk(
        self,
        *,
        session_id: UUID,
        chunk: AudioChunk,
        session_audio_root: Path,
        sample_rate_hz: int,
        on_application_event: Callable[[ApplicationEvent], None] | None,
        on_segment: Callable[[TranscriptSegment], None] | None,
        transcription_enabled: bool = True,
    ) -> None:
        log = get_logger(component="recorder", session_id=str(session_id))

        # Persist audio to the full-session WAV first so the meeting can still be
        # finalized offline even when live transcription is unavailable.
        append_chunk_with_timeline(
            session_audio_root=session_audio_root,
            chunk_wav=chunk.path,
            sample_rate_hz=sample_rate_hz,
            wall_started_at=chunk.started_at,
            wall_ended_at=chunk.ended_at,
            fallback_duration_seconds=chunk.duration_seconds,
            log=log,
        )

        if not transcription_enabled:
            # Live transcription disabled (e.g. model unavailable); audio is kept above.
            self._discard_chunk_audio(chunk, log)
            await asyncio.sleep(0)
            return

        log.info("transcription_started", chunk_id=str(chunk.id))
        _emit(
            on_application_event,
            TranscriptionChunkStarted(session_id=session_id, chunk_id=chunk.id, at=utc_now()),
        )

        use_dual = (
            chunk.channels == 2
            and self.audio_stereo_mode == "dual_path"
            and transcriber_supports_dual_path(self.transcriber)
        )
        if chunk.channels == 2 and self.audio_stereo_mode == "dual_path" and not use_dual:
            log.warning(
                "dual_path_stereo_ignored",
                message="AUDIO_STEREO_MODE=dual_path requires faster_whisper; using mixdown.",
            )

        if use_dual:
            await self._transcribe_dual_path(
                session_id=session_id,
                chunk=chunk,
                sample_rate_hz=sample_rate_hz,
                on_application_event=on_application_event,
                on_segment=on_segment,
                log=log,
            )
        else:
            await self._transcribe_mixdown(
                session_id=session_id,
                chunk=chunk,
                sample_rate_hz=sample_rate_hz,
                on_application_event=on_application_event,
                on_segment=on_segment,
                log=log,
            )

        await asyncio.sleep(0)

    async def _transcribe_dual_path(
        self,
        *,
        session_id: UUID,
        chunk: AudioChunk,
        sample_rate_hz: int,
        on_application_event: Callable[[ApplicationEvent], None] | None,
        on_segment: Callable[[TranscriptSegment], None] | None,
        log: Any,
    ) -> None:
        """Stereo path: split mic/system channels and transcribe each separately so the
        provider can attribute speakers. Preserves per-segment speaker labels and reports
        the detected speakers — unlike the mixdown path, which forces ``unknown``."""
        temp_paths: list[Path] = []
        try:
            mic_path = extract_mono_channel_wav(chunk.path, 0, sample_rate_hz=sample_rate_hz)
            sys_path = extract_mono_channel_wav(chunk.path, 1, sample_rate_hz=sample_rate_hz)
            temp_paths.extend([mic_path, sys_path])
            try:
                segments = await self.transcriber.transcribe_stereo_chunk(  # type: ignore[attr-defined]
                    chunk=chunk, mic_path=mic_path, sys_path=sys_path
                )
            except TranscriptionProviderError as e:
                if not e.recoverable:
                    raise
                log.warning(
                    "transcription_chunk_failed",
                    chunk_id=str(chunk.id),
                    error=str(e),
                    exc_info=True,
                )
                await self._skip_transcription_chunk(
                    chunk=chunk,
                    on_application_event=on_application_event,
                    event=TranscriptionChunkFailed(
                        session_id=session_id,
                        chunk_id=chunk.id,
                        message=str(e),
                        at=utc_now(),
                    ),
                    log=log,
                )
                return
            except Exception as e:
                log.exception("transcription_chunk_failed", chunk_id=str(chunk.id))
                await self._skip_transcription_chunk(
                    chunk=chunk,
                    on_application_event=on_application_event,
                    event=TranscriptionChunkFailed(
                        session_id=session_id,
                        chunk_id=chunk.id,
                        message=str(e),
                        at=utc_now(),
                    ),
                    log=log,
                )
                return
            if not segments:
                log.warning("transcription_empty_chunk", chunk_id=str(chunk.id))
                await self._skip_transcription_chunk(
                    chunk=chunk,
                    on_application_event=on_application_event,
                    event=TranscriptionChunkEmpty(
                        session_id=session_id,
                        chunk_id=chunk.id,
                        at=utc_now(),
                    ),
                    log=log,
                )
                return
            detected = frozenset({s.speaker for s in segments if s.speaker})
            for segment in segments:
                self.transcripts.append(segment)
                log.info("transcript_segment_saved", segment_id=str(segment.id))
                _emit(
                    on_application_event,
                    TranscriptSegmentPersisted(segment=segment, at=utc_now()),
                )
                if on_segment is not None:
                    on_segment(segment)
            last_seg = segments[-1]
            _emit(
                on_application_event,
                TranscriptionChunkCompleted(session_id=session_id, chunk_id=chunk.id, at=utc_now()),
            )
            _emit(
                on_application_event,
                DiarizationChunkCompleted(
                    segment=last_seg,
                    detected_speakers=detected,
                    at=utc_now(),
                ),
            )
        finally:
            for p in temp_paths:
                try:
                    p.unlink(missing_ok=True)
                except OSError:
                    pass

        self._discard_chunk_audio(chunk, log)

    async def _transcribe_mixdown(
        self,
        *,
        session_id: UUID,
        chunk: AudioChunk,
        sample_rate_hz: int,
        on_application_event: Callable[[ApplicationEvent], None] | None,
        on_segment: Callable[[TranscriptSegment], None] | None,
        log: Any,
    ) -> None:
        """Mono path: mix a stereo chunk down (or use mono as-is) and transcribe once.
        There is no speaker attribution, so the single segment is forced to ``unknown``."""
        temp_paths: list[Path] = []
        try:
            work_chunk = chunk
            if chunk.channels == 2:
                mono_p = rms_mixdown_to_mono_wav(chunk.path, sample_rate_hz=sample_rate_hz)
                temp_paths.append(mono_p)
                work_chunk = chunk.model_copy(
                    update={
                        "path": mono_p,
                        "channels": 1,
                    }
                )
            try:
                segment = await self.transcriber.transcribe(chunk=work_chunk)
            except EmptyTranscriptionError:
                log.warning("transcription_empty_chunk", chunk_id=str(chunk.id))
                await self._skip_transcription_chunk(
                    chunk=chunk,
                    on_application_event=on_application_event,
                    event=TranscriptionChunkEmpty(
                        session_id=session_id,
                        chunk_id=chunk.id,
                        at=utc_now(),
                    ),
                    log=log,
                )
                return
            except TranscriptionProviderError as e:
                if not e.recoverable:
                    raise
                log.warning(
                    "transcription_chunk_failed",
                    chunk_id=str(chunk.id),
                    error=str(e),
                    exc_info=True,
                )
                await self._skip_transcription_chunk(
                    chunk=chunk,
                    on_application_event=on_application_event,
                    event=TranscriptionChunkFailed(
                        session_id=session_id,
                        chunk_id=chunk.id,
                        message=str(e),
                        at=utc_now(),
                    ),
                    log=log,
                )
                return
            except Exception as e:
                log.exception("transcription_chunk_failed", chunk_id=str(chunk.id))
                await self._skip_transcription_chunk(
                    chunk=chunk,
                    on_application_event=on_application_event,
                    event=TranscriptionChunkFailed(
                        session_id=session_id,
                        chunk_id=chunk.id,
                        message=str(e),
                        at=utc_now(),
                    ),
                    log=log,
                )
                return

            segment = segment.model_copy(
                update={
                    "speaker": "unknown",
                    "chunk_id": chunk.id,
                }
            )
            _emit(
                on_application_event,
                TranscriptionChunkCompleted(session_id=session_id, chunk_id=chunk.id, at=utc_now()),
            )
            _emit(
                on_application_event,
                DiarizationChunkCompleted(
                    segment=segment,
                    detected_speakers=frozenset(),
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
        finally:
            for p in temp_paths:
                try:
                    p.unlink(missing_ok=True)
                except OSError:
                    pass

        self._discard_chunk_audio(chunk, log)

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
        session_audio_root = session_audio_dir(self.data_dir, session_id)
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

        # Load the transcription model once up front (downloads on first use). If it
        # fails, keep recording audio for offline finalize but skip live transcription
        # instead of retrying — and silently swallowing — the failure on every chunk.
        transcription_enabled = True
        warm_up = getattr(self.transcriber, "warm_up", None)
        if callable(warm_up):
            try:
                await warm_up()
            except Exception as e:
                transcription_enabled = False
                log.warning("transcription_warm_up_failed", error=str(e), exc_info=True)
                _emit(
                    on_application_event,
                    TranscriptionUnavailable(
                        session_id=session_id,
                        message=(
                            f"Live transcription unavailable: {e}. Audio is still being "
                            "recorded — run Speaker ID / finalize afterwards to transcribe."
                        ),
                        at=utc_now(),
                    ),
                )

        try:
            while True:
                try:
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
                except asyncio.CancelledError:
                    log.info("recording_cancelled")
                    _emit(
                        on_application_event,
                        RecordingStopped(session_id=session_id, at=utc_now()),
                    )
                    return

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

                ingest_task = asyncio.create_task(
                    self._ingest_captured_chunk(
                        session_id=session_id,
                        chunk=chunk,
                        session_audio_root=session_audio_root,
                        sample_rate_hz=sample_rate_hz,
                        on_application_event=on_application_event,
                        on_segment=on_segment,
                        transcription_enabled=transcription_enabled,
                    )
                )
                try:
                    await asyncio.shield(ingest_task)
                except asyncio.CancelledError:
                    log.info("recording_stop_draining_chunk", chunk_id=str(chunk.id))
                    await ingest_task
                    log.info("recording_cancelled")
                    _emit(
                        on_application_event,
                        RecordingStopped(session_id=session_id, at=utc_now()),
                    )
                    return
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
