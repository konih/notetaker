"""Detect slide candidates without transcribing or writing to the database."""

from __future__ import annotations

import asyncio
import json
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from uuid import UUID

from live_meeting_transcriber.application.slide_review import review_slide_candidates
from live_meeting_transcriber.application.video_session_storage import (
    VideoSessionStorageError,
    read_source_media_video_path,
    session_slides_dir,
    session_slides_manifest_path,
)
from live_meeting_transcriber.config.settings import Settings
from live_meeting_transcriber.domain.exceptions import SlideDetectionError
from live_meeting_transcriber.domain.models import SlideCandidate, SlideDetectionParams
from live_meeting_transcriber.domain.ports import (
    MediaImporter,
    MeetingSessionRepository,
    SlideDetectionTools,
)


class SlidePreviewError(RuntimeError):
    pass


@dataclass(frozen=True)
class SlidePreviewResult:
    session_id: UUID
    strategy: str
    duration_seconds: float
    video_path: Path
    candidates: list[SlideCandidate]
    preview_dir: Path


@dataclass(frozen=True)
class SlidePreviewService:
    settings: Settings
    sessions: MeetingSessionRepository
    # Media/slide toolkits behind ports (A9); wired from the container.
    media: MediaImporter
    slide_tools: SlideDetectionTools

    async def preview(
        self,
        *,
        session_id: UUID,
        strategy: str | None = None,
        params: SlideDetectionParams | None = None,
        preview_dir: Path | None = None,
    ) -> SlidePreviewResult:
        session = self.sessions.get(session_id)
        if session is None:
            raise SlidePreviewError(f"Unknown session {session_id}")

        data_dir = self.settings.ensure_data_dir()
        try:
            video_path = await asyncio.to_thread(read_source_media_video_path, data_dir, session_id)
        except VideoSessionStorageError as e:
            raise SlidePreviewError(str(e)) from e
        duration = await asyncio.to_thread(self.media.probe_duration_seconds, video_path)

        detection_params = params or self.settings.slide_detection_params()
        resolved_strategy = strategy or self.settings.video_slide_strategy
        strat = self.slide_tools.build_strategy(resolved_strategy)

        out_preview = (
            preview_dir or (data_dir / "imports" / "slide_previews" / str(session_id)).resolve()
        )
        if out_preview.exists():
            shutil.rmtree(out_preview, ignore_errors=True)
        out_preview.mkdir(parents=True, exist_ok=True)

        try:
            candidates = await asyncio.to_thread(
                strat.detect,
                video_path=video_path,
                duration_seconds=duration,
                params=detection_params,
                preview_dir=out_preview,
            )
        except SlideDetectionError as e:
            raise SlidePreviewError(str(e)) from e

        return SlidePreviewResult(
            session_id=session_id,
            strategy=str(resolved_strategy),
            duration_seconds=duration,
            video_path=video_path,
            candidates=candidates,
            preview_dir=out_preview,
        )

    async def apply(
        self,
        *,
        session_id: UUID,
        candidates: list[SlideCandidate],
        accept_all: bool = False,
        reject_all: bool = False,
        prompt_fn: Callable[[str], str] | None = None,
        echo_fn: Callable[[str], None] | None = None,
    ) -> int:
        session = self.sessions.get(session_id)
        if session is None:
            raise SlidePreviewError(f"Unknown session {session_id}")

        approved = review_slide_candidates(
            candidates,
            prompt_fn=prompt_fn,
            echo_fn=echo_fn,
            accept_all=accept_all,
            reject_all=reject_all,
        )
        if not approved:
            return 0

        data_dir = self.settings.ensure_data_dir()
        try:
            video_path = await asyncio.to_thread(read_source_media_video_path, data_dir, session_id)
        except VideoSessionStorageError as e:
            raise SlidePreviewError(str(e)) from e
        slides_dir = session_slides_dir(data_dir, session_id)
        slides_dir.mkdir(parents=True, exist_ok=True)
        manifest: list[dict[str, object]] = []

        for i, cand in enumerate(approved):
            dest = slides_dir / f"slide_{i:03d}_{cand.timestamp_seconds:.1f}s.png"
            if cand.preview_path is not None and cand.preview_path.is_file():
                shutil.copy2(cand.preview_path, dest)
            else:
                await asyncio.to_thread(
                    self.slide_tools.extract_frame,
                    video_path=video_path,
                    timestamp_seconds=cand.timestamp_seconds,
                    dest_png=dest,
                )
            captured_at = session.started_at + timedelta(seconds=cand.timestamp_seconds)
            manifest.append(
                {
                    "index": i,
                    "timestamp_seconds": cand.timestamp_seconds,
                    "captured_at": captured_at.isoformat(),
                    "path": dest.name,
                    "change_score": cand.change_score,
                }
            )

        manifest_path = session_slides_manifest_path(data_dir, session_id)
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return len(approved)
