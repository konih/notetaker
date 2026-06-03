"""Detect slide changes using ffmpeg's scene-change score filter."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from live_meeting_transcriber.domain.models import SlideCandidate, SlideDetectionParams
from live_meeting_transcriber.video.slide_common import (
    SlideDetectionError,
    effective_min_slide_interval,
    maybe_save_preview,
)

_SCENE_PTS_RE = re.compile(r"pts_time:([0-9.]+)")
_SCENE_SCORE_RE = re.compile(r"scene_score=([0-9.]+)")


class FfmpegSceneStrategy:
    """Use ``select='gt(scene,THRESH)'`` to find scene cuts, then enforce pacing caps."""

    def detect(
        self,
        *,
        video_path: Path,
        duration_seconds: float,
        params: SlideDetectionParams,
        preview_dir: Path | None = None,
    ) -> list[SlideCandidate]:
        if duration_seconds <= 0:
            return []
        if params.max_candidates <= 0:
            return []

        if preview_dir is not None:
            preview_dir.mkdir(parents=True, exist_ok=True)

        threshold = max(0.01, min(1.0, params.change_threshold))
        raw = self._probe_scene_timestamps(video_path=video_path, threshold=threshold)
        if not raw and duration_seconds > 0:
            raw = [(0.0, 1.0)]

        min_interval = effective_min_slide_interval(
            params.min_slide_interval_seconds,
            duration_seconds,
        )

        candidates: list[SlideCandidate] = []
        last_slide_at = -min_interval
        for ts, score in raw:
            if ts >= duration_seconds:
                continue
            if ts > params.sample_interval_seconds * 0.5 and (ts - last_slide_at < min_interval):
                continue
            preview = maybe_save_preview(
                video_path=video_path,
                timestamp_seconds=ts,
                preview_dir=preview_dir,
                index=len(candidates),
            )
            candidates.append(
                SlideCandidate(timestamp_seconds=ts, change_score=score, preview_path=preview)
            )
            last_slide_at = ts
            if len(candidates) >= params.max_candidates:
                break

        if not candidates and duration_seconds > 0:
            preview = maybe_save_preview(
                video_path=video_path,
                timestamp_seconds=0.0,
                preview_dir=preview_dir,
                index=0,
            )
            candidates.append(
                SlideCandidate(timestamp_seconds=0.0, change_score=1.0, preview_path=preview)
            )

        return candidates

    def _probe_scene_timestamps(
        self, *, video_path: Path, threshold: float
    ) -> list[tuple[float, float]]:
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "info",
            "-i",
            str(video_path),
            "-vf",
            f"select='gt(scene,{threshold})',showinfo",
            "-f",
            "null",
            "-",
        ]
        try:
            proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
        except FileNotFoundError as e:
            raise SlideDetectionError("ffmpeg not found; install ffmpeg") from e

        combined = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode not in (0, 255) and "showinfo" not in combined:
            detail = (proc.stderr or "").strip()
            raise SlideDetectionError(detail or "ffmpeg scene detection failed")

        out: list[tuple[float, float]] = []
        pending_ts: float | None = None
        pending_score: float | None = None
        for line in combined.splitlines():
            ts_match = _SCENE_PTS_RE.search(line)
            score_match = _SCENE_SCORE_RE.search(line)
            if ts_match:
                new_ts = float(ts_match.group(1))
                if pending_ts is not None:
                    out.append(
                        (pending_ts, pending_score if pending_score is not None else threshold)
                    )
                pending_ts = new_ts
                pending_score = float(score_match.group(1)) if score_match else None
            elif score_match and pending_ts is not None:
                pending_score = float(score_match.group(1))

        if pending_ts is not None:
            out.append((pending_ts, pending_score if pending_score is not None else threshold))

        deduped: list[tuple[float, float]] = []
        seen: set[float] = set()
        for ts, score in sorted(out, key=lambda x: x[0]):
            key = round(ts, 2)
            if key in seen:
                continue
            seen.add(key)
            deduped.append((ts, score))
        return deduped
