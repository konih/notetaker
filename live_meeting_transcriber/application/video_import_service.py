"""Import a video file or URL: transcribe audio and optionally extract slide screenshots."""

from __future__ import annotations

import asyncio
import json
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from live_meeting_transcriber.application.slide_review import review_slide_candidates
from live_meeting_transcriber.application.video_session_storage import (
    session_slides_dir,
    session_slides_manifest_path,
    write_source_media_manifest,
)
from live_meeting_transcriber.audio.media_import import (
    MediaImportError,
    extract_audio_to_wav,
    probe_media_duration_seconds,
)
from live_meeting_transcriber.audio.media_source import (
    MediaSourceError,
    media_title_from_source,
    resolve_media_source,
)
from live_meeting_transcriber.audio.session_recording import (
    full_session_wav_path,
    session_audio_dir,
)
from live_meeting_transcriber.audio.stereo import rms_mixdown_to_mono_wav
from live_meeting_transcriber.audio.timeline import AudioTimelineEntry, append_timeline_entry
from live_meeting_transcriber.audio.wav_segment import (
    MIN_TRANSCRIPTION_CHUNK_SECONDS,
    WavSegmentExtractionError,
    extract_wav_time_range,
    safe_wav_duration_seconds,
    wav_is_transcribable,
)
from live_meeting_transcriber.config.settings import Settings
from live_meeting_transcriber.domain.exceptions import (
    EmptyTranscriptionError,
    TranscriptionProviderError,
)
from live_meeting_transcriber.domain.models import (
    AudioChunk,
    MeetingSession,
    SlideDetectionParams,
    TranscriptSegment,
)
from live_meeting_transcriber.domain.ports import (
    MeetingSessionRepository,
    TranscriptionProvider,
    TranscriptRepository,
)
from live_meeting_transcriber.observability.logging import get_logger
from live_meeting_transcriber.video.slide_common import SlideDetectionError, extract_slide_frame
from live_meeting_transcriber.video.strategies.factory import (
    SlideStrategyName,
    build_slide_strategy,
)


class VideoImportError(RuntimeError):
    pass


# When chunk size is not overridden on the CLI, transcribe the full WAV in one request
# for typical presentation-length imports (avoids tiny tail chunks and needless API calls).
_VIDEO_IMPORT_SINGLE_CHUNK_MAX_SECONDS = 120


@dataclass(frozen=True)
class TranscriptionSummary:
    chunks: int
    segments: int
    skipped_silent: int
    skipped_empty: int
    failed: int
    failure_messages: tuple[str, ...] = ()

    @property
    def has_failures(self) -> bool:
        return self.failed > 0

    def status_message(self) -> str | None:
        """Human-readable warning when transcription did not fully succeed."""
        if self.segments == 0 and self.chunks > 0:
            parts = [
                f"No transcript segments from {self.chunks} chunk(s)",
            ]
            if self.skipped_silent:
                parts.append(f"{self.skipped_silent} silent")
            if self.skipped_empty:
                parts.append(f"{self.skipped_empty} empty")
            if self.failed:
                parts.append(f"{self.failed} failed")
            msg = "; ".join(parts)
            if self.failure_messages:
                msg += f". {self.failure_messages[0]}"
            return msg
        if not self.has_failures:
            return None
        msg = (
            f"Partial transcription: {self.segments} segment(s) from {self.chunks} chunk(s); "
            f"{self.failed} chunk(s) failed"
        )
        if self.skipped_empty:
            msg += f"; {self.skipped_empty} empty"
        if self.skipped_silent:
            msg += f"; {self.skipped_silent} silent"
        if self.failure_messages:
            msg += f". First error: {self.failure_messages[0]}"
        return msg


@dataclass(frozen=True)
class VideoImportProgress:
    phase: Literal["transcribing", "slides"]
    chunk_index: int = 0
    chunk_total: int = 0
    offset_seconds: float = 0.0
    segments_so_far: int = 0


@dataclass(frozen=True)
class VideoImportResult:
    session_id: UUID
    segment_count: int
    slide_count: int
    video_path: Path
    transcription: TranscriptionSummary | None = None


@dataclass(frozen=True)
class VideoImportService:
    settings: Settings
    sessions: MeetingSessionRepository
    transcripts: TranscriptRepository
    transcriber: TranscriptionProvider

    async def import_video(
        self,
        *,
        source: str,
        title: str | None = None,
        chunk_seconds: int | None = None,
        extract_slides: bool = True,
        accept_all_slides: bool = False,
        reject_all_slides: bool = False,
        slide_strategy: SlideStrategyName | str | None = None,
        slide_params: SlideDetectionParams | None = None,
        on_segment: Callable[[TranscriptSegment], None] | None = None,
        on_progress: Callable[[VideoImportProgress], None] | None = None,
        slide_prompt_fn: Callable[[str], str] | None = None,
        slide_echo_fn: Callable[[str], None] | None = None,
        skip_transcription: bool = False,
    ) -> VideoImportResult:
        log = get_logger(component="video_import")
        data_dir = self.settings.ensure_data_dir()
        download_dir = (data_dir / "imports" / "downloads").resolve()
        download_dir.mkdir(parents=True, exist_ok=True)

        try:
            video_path = await asyncio.to_thread(
                resolve_media_source,
                source=source,
                download_dir=download_dir,
            )
        except MediaSourceError as e:
            raise VideoImportError(str(e)) from e

        session_title = (title or media_title_from_source(source, video_path)).strip()
        if not session_title:
            session_title = "Video"

        session = self.sessions.create(MeetingSession(title=session_title))
        session_id = session.id
        log.info("video_import_started", session_id=str(session_id), source=source)

        audio_root = session_audio_dir(data_dir, session_id)
        full_wav = full_session_wav_path(audio_root)
        sample_rate = self.settings.audio_sample_rate
        channels = self.settings.audio_channels
        configured_chunk = chunk_seconds or self.settings.audio_chunk_seconds
        implicit_chunk = chunk_seconds is None

        try:
            duration = await asyncio.to_thread(probe_media_duration_seconds, video_path)
            await asyncio.to_thread(
                extract_audio_to_wav,
                video_path=video_path,
                dest_wav=full_wav,
                sample_rate_hz=sample_rate,
                channels=channels,
            )
        except MediaImportError as e:
            raise VideoImportError(str(e)) from e

        wav_duration = await asyncio.to_thread(safe_wav_duration_seconds, full_wav)
        if wav_duration <= 0:
            raise VideoImportError("extracted session audio has zero duration")

        timeline_duration = min(duration, wav_duration)
        started_at = session.started_at
        append_timeline_entry(
            audio_root,
            AudioTimelineEntry(
                audio_start_sec=0.0,
                audio_end_sec=timeline_duration,
                wall_started_at=started_at,
                wall_ended_at=started_at + timedelta(seconds=timeline_duration),
            ),
        )
        write_source_media_manifest(
            data_dir=data_dir,
            session_id=session_id,
            video_path=video_path,
            source=source,
        )

        transcription_summary: TranscriptionSummary | None = None
        seg_count = 0
        if not skip_transcription:
            effective_chunk = _effective_video_chunk_seconds(
                wav_duration,
                configured_chunk_seconds=configured_chunk,
                implicit_chunk=implicit_chunk,
            )
            chunk_dir = (data_dir / "chunks" / str(session_id)).resolve()
            chunk_dir.mkdir(parents=True, exist_ok=True)
            transcription_summary = await self._transcribe_wav_in_chunks(
                session_id=session_id,
                full_wav=full_wav,
                duration_seconds=wav_duration,
                chunk_seconds=effective_chunk,
                sample_rate_hz=sample_rate,
                channels=channels,
                chunk_dir=chunk_dir,
                session_started_at=started_at,
                on_segment=on_segment,
                on_progress=on_progress,
            )
            seg_count = transcription_summary.segments
            status = transcription_summary.status_message()
            if transcription_summary.segments == 0 and transcription_summary.chunks > 0:
                raise VideoImportError(status or "Transcription produced no segments")
            if status is not None:
                log.warning("transcription_partial", session_id=str(session_id), detail=status)

        slide_count = 0
        if extract_slides and not reject_all_slides:
            if on_progress is not None:
                on_progress(VideoImportProgress(phase="slides"))
            slide_count = await self._extract_reviewed_slides(
                session_id=session_id,
                video_path=video_path,
                duration_seconds=duration,
                session_started_at=started_at,
                accept_all=accept_all_slides,
                reject_all=reject_all_slides,
                slide_strategy=slide_strategy,
                slide_params=slide_params,
                prompt_fn=slide_prompt_fn,
                echo_fn=slide_echo_fn,
            )

        self.sessions.end(session_id)

        log.info(
            "video_import_completed",
            session_id=str(session_id),
            segments=seg_count,
            slides=slide_count,
            transcription_chunks=transcription_summary.chunks if transcription_summary else 0,
            transcription_failed=transcription_summary.failed if transcription_summary else 0,
        )
        return VideoImportResult(
            session_id=session_id,
            segment_count=seg_count,
            slide_count=slide_count,
            video_path=video_path,
            transcription=transcription_summary,
        )

    async def _transcribe_wav_in_chunks(
        self,
        *,
        session_id: UUID,
        full_wav: Path,
        duration_seconds: float,
        chunk_seconds: float,
        sample_rate_hz: int,
        channels: int,
        chunk_dir: Path,
        session_started_at: datetime,
        on_segment: Callable[[TranscriptSegment], None] | None,
        on_progress: Callable[[VideoImportProgress], None] | None,
    ) -> TranscriptionSummary:
        log = get_logger(component="video_import", session_id=str(session_id))
        chunk_dir.mkdir(parents=True, exist_ok=True)
        chunk_total = _planned_chunk_count(duration_seconds, chunk_seconds)
        segments = 0
        skipped_silent = 0
        skipped_empty = 0
        failed = 0
        failure_messages: list[str] = []
        chunk_index = 0
        offset = 0.0

        while offset < duration_seconds - 1e-6:
            end = min(offset + chunk_seconds, duration_seconds)
            span = end - offset
            if span < MIN_TRANSCRIPTION_CHUNK_SECONDS:
                log.debug("skip_sub_minimum_chunk", offset=offset, duration_seconds=span)
                break

            chunk_index += 1
            if on_progress is not None:
                on_progress(
                    VideoImportProgress(
                        phase="transcribing",
                        chunk_index=chunk_index,
                        chunk_total=chunk_total,
                        offset_seconds=offset,
                        segments_so_far=segments,
                    )
                )

            chunk_id = uuid4()
            chunk_path = chunk_dir / f"{chunk_id}.wav"
            try:
                await asyncio.to_thread(
                    extract_wav_time_range,
                    src=full_wav,
                    dest=chunk_path,
                    start_seconds=offset,
                    end_seconds=end,
                    sample_rate_hz=sample_rate_hz,
                    channels=channels,
                )
            except WavSegmentExtractionError as e:
                failed += 1
                reason = f"chunk {chunk_index} @ {offset:.1f}s: {e}"
                failure_messages.append(reason)
                log.warning("chunk_extract_failed", offset=offset, error=str(e))
                offset = end
                await asyncio.sleep(0)
                continue

            work_path = chunk_path
            temp_mono: Path | None = None
            if channels == 2:
                temp_mono = await asyncio.to_thread(
                    rms_mixdown_to_mono_wav, chunk_path, sample_rate_hz=sample_rate_hz
                )
                work_path = temp_mono

            if not wav_is_transcribable(work_path):
                skipped_silent += 1
                log.debug("skip_empty_chunk", offset=offset)
                if temp_mono is not None:
                    temp_mono.unlink(missing_ok=True)
                if not self.settings.keep_audio_chunks:
                    chunk_path.unlink(missing_ok=True)
                offset = end
                await asyncio.sleep(0)
                continue

            chunk_started = session_started_at + timedelta(seconds=offset)
            chunk_ended = session_started_at + timedelta(seconds=end)
            chunk = AudioChunk(
                id=chunk_id,
                session_id=session_id,
                started_at=chunk_started,
                ended_at=chunk_ended,
                path=work_path,
                sample_rate_hz=sample_rate_hz,
                channels=1 if temp_mono is not None else channels,
            )

            try:
                segment = await self.transcriber.transcribe(chunk=chunk)
            except EmptyTranscriptionError:
                skipped_empty += 1
                log.warning("empty_chunk", offset=offset, chunk_index=chunk_index)
            except TranscriptionProviderError as e:
                if not e.recoverable:
                    raise
                failed += 1
                reason = f"chunk {chunk_index} @ {offset:.1f}s: {e}"
                failure_messages.append(reason)
                log.warning("chunk_transcribe_failed", offset=offset, error=str(e))
            except Exception as e:
                failed += 1
                reason = f"chunk {chunk_index} @ {offset:.1f}s: {e}"
                failure_messages.append(reason)
                log.exception("chunk_transcribe_unexpected", offset=offset)
            else:
                segment = segment.model_copy(
                    update={"speaker": "unknown", "chunk_id": chunk_id},
                )
                self.transcripts.append(segment)
                segments += 1
                if on_segment is not None:
                    on_segment(segment)
            finally:
                if temp_mono is not None:
                    temp_mono.unlink(missing_ok=True)
                if not self.settings.keep_audio_chunks:
                    chunk_path.unlink(missing_ok=True)

            offset = end
            await asyncio.sleep(0)

        summary = TranscriptionSummary(
            chunks=chunk_index,
            segments=segments,
            skipped_silent=skipped_silent,
            skipped_empty=skipped_empty,
            failed=failed,
            failure_messages=tuple(failure_messages),
        )
        log.info(
            "transcription_chunks_complete",
            chunks=summary.chunks,
            segments=summary.segments,
            skipped_silent=summary.skipped_silent,
            skipped_empty=summary.skipped_empty,
            failed=summary.failed,
        )
        return summary

    async def _extract_reviewed_slides(
        self,
        *,
        session_id: UUID,
        video_path: Path,
        duration_seconds: float,
        session_started_at: datetime,
        accept_all: bool,
        reject_all: bool,
        slide_strategy: SlideStrategyName | str | None,
        slide_params: SlideDetectionParams | None,
        prompt_fn: Callable[[str], str] | None,
        echo_fn: Callable[[str], None] | None,
    ) -> int:
        preview_dir = (
            self.settings.ensure_data_dir() / "imports" / "slide_previews" / str(session_id)
        )
        params = slide_params or self.settings.slide_detection_params()
        strategy = build_slide_strategy(slide_strategy, settings=self.settings)
        try:
            candidates = await asyncio.to_thread(
                strategy.detect,
                video_path=video_path,
                duration_seconds=duration_seconds,
                params=params,
                preview_dir=preview_dir,
            )
        except SlideDetectionError as e:
            raise VideoImportError(str(e)) from e

        approved = review_slide_candidates(
            candidates,
            prompt_fn=prompt_fn,
            echo_fn=echo_fn,
            accept_all=accept_all,
            reject_all=reject_all,
        )
        if not approved:
            shutil.rmtree(preview_dir, ignore_errors=True)
            return 0

        slides_dir = session_slides_dir(self.settings.ensure_data_dir(), session_id)
        slides_dir.mkdir(parents=True, exist_ok=True)
        manifest: list[dict[str, object]] = []

        for i, cand in enumerate(approved):
            dest = slides_dir / f"slide_{i:03d}_{cand.timestamp_seconds:.1f}s.png"
            if cand.preview_path is not None and cand.preview_path.is_file():
                shutil.copy2(cand.preview_path, dest)
            else:
                await asyncio.to_thread(
                    extract_slide_frame,
                    video_path=video_path,
                    timestamp_seconds=cand.timestamp_seconds,
                    dest_png=dest,
                )
            captured_at = session_started_at + timedelta(seconds=cand.timestamp_seconds)
            manifest.append(
                {
                    "index": i,
                    "timestamp_seconds": cand.timestamp_seconds,
                    "captured_at": captured_at.isoformat(),
                    "path": dest.name,
                    "change_score": cand.change_score,
                }
            )

        manifest_path = session_slides_manifest_path(self.settings.ensure_data_dir(), session_id)
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        shutil.rmtree(preview_dir, ignore_errors=True)
        return len(approved)


def _planned_chunk_count(duration_seconds: float, chunk_seconds: float) -> int:
    count = 0
    offset = 0.0
    while offset < duration_seconds - 1e-6:
        end = min(offset + chunk_seconds, duration_seconds)
        if end - offset < MIN_TRANSCRIPTION_CHUNK_SECONDS:
            break
        count += 1
        offset = end
    return count


def _effective_video_chunk_seconds(
    wav_duration: float,
    *,
    configured_chunk_seconds: int,
    implicit_chunk: bool,
) -> float:
    """Pick chunk size for video import: one request when the file fits."""
    if wav_duration <= configured_chunk_seconds:
        return wav_duration
    if implicit_chunk and wav_duration <= _VIDEO_IMPORT_SINGLE_CHUNK_MAX_SECONDS:
        return wav_duration
    return float(configured_chunk_seconds)
