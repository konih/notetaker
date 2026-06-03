"""Detect slide changes by comparing periodically sampled grayscale frames."""

from __future__ import annotations

from pathlib import Path

from live_meeting_transcriber.domain.models import SlideCandidate, SlideDetectionParams
from live_meeting_transcriber.video.slide_common import (
    SlideDetectionError,
    effective_min_slide_interval,
    extract_gray_frame_bytes,
    maybe_save_preview,
)


def mean_absolute_difference(a: bytes, b: bytes) -> float:
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    total = sum(abs(a[i] - b[i]) for i in range(n))
    return total / float(n)


class FrameDiffStrategy:
    """Sample frames periodically; flag large visual changes as slide transitions."""

    def detect(
        self,
        *,
        video_path: Path,
        duration_seconds: float,
        params: SlideDetectionParams,
        preview_dir: Path | None = None,
        thumb_width: int = 160,
        thumb_height: int = 90,
    ) -> list[SlideCandidate]:
        if duration_seconds <= 0:
            return []
        if params.sample_interval_seconds <= 0:
            raise SlideDetectionError("sample_interval_seconds must be positive")
        if params.min_slide_interval_seconds < 0:
            raise SlideDetectionError("min_slide_interval_seconds must be non-negative")
        if params.max_candidates <= 0:
            return []

        if preview_dir is not None:
            preview_dir.mkdir(parents=True, exist_ok=True)

        timestamps: list[float] = []
        t = 0.0
        while t < duration_seconds:
            timestamps.append(t)
            t += params.sample_interval_seconds

        min_interval = effective_min_slide_interval(
            params.min_slide_interval_seconds,
            duration_seconds,
        )

        candidates: list[SlideCandidate] = []
        prev_frame: bytes | None = None
        last_slide_at = -min_interval

        for ts in timestamps:
            try:
                frame = extract_gray_frame_bytes(
                    video_path=video_path,
                    timestamp_seconds=ts,
                    width=thumb_width,
                    height=thumb_height,
                )
            except SlideDetectionError:
                continue
            if not frame:
                continue
            if prev_frame is None:
                prev_frame = frame
                if ts <= params.sample_interval_seconds * 0.5:
                    preview = maybe_save_preview(
                        video_path=video_path,
                        timestamp_seconds=ts,
                        preview_dir=preview_dir,
                        index=len(candidates),
                    )
                    candidates.append(
                        SlideCandidate(
                            timestamp_seconds=ts,
                            change_score=1.0,
                            preview_path=preview,
                        )
                    )
                    last_slide_at = ts
                continue

            score = mean_absolute_difference(prev_frame, frame) / 255.0
            prev_frame = frame
            if score < params.change_threshold:
                continue
            if ts - last_slide_at < min_interval:
                continue

            preview = maybe_save_preview(
                video_path=video_path,
                timestamp_seconds=ts,
                preview_dir=preview_dir,
                index=len(candidates),
            )
            candidates.append(
                SlideCandidate(
                    timestamp_seconds=ts,
                    change_score=score,
                    preview_path=preview,
                )
            )
            last_slide_at = ts
            if len(candidates) >= params.max_candidates:
                break

        return candidates
