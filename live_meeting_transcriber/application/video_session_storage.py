"""On-disk paths and manifests for imported video sessions (slides, source media)."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

from live_meeting_transcriber.audio.session_recording import session_audio_dir


class VideoSessionStorageError(RuntimeError):
    pass


def session_slides_dir(data_dir: Path, session_id: UUID) -> Path:
    return session_audio_dir(data_dir, session_id) / "slides"


def session_slides_manifest_path(data_dir: Path, session_id: UUID) -> Path:
    return session_slides_dir(data_dir, session_id) / "slides.json"


def source_media_manifest_path(data_dir: Path, session_id: UUID) -> Path:
    return session_audio_dir(data_dir, session_id) / "source_media.json"


def write_source_media_manifest(
    *,
    data_dir: Path,
    session_id: UUID,
    video_path: Path,
    source: str,
) -> Path:
    path = source_media_manifest_path(data_dir, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "video_path": str(video_path.resolve()),
        "source": source,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def read_source_media_video_path(data_dir: Path, session_id: UUID) -> Path:
    manifest = source_media_manifest_path(data_dir, session_id)
    if not manifest.is_file():
        msg = (
            f"No source_media.json for session {session_id}; "
            "import the video with transcribe-video first."
        )
        raise VideoSessionStorageError(msg)
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        video_path = Path(str(data["video_path"]))
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        raise VideoSessionStorageError(f"Invalid source_media.json at {manifest}") from e
    if not video_path.is_file():
        raise VideoSessionStorageError(f"Source video missing: {video_path}")
    return video_path.resolve()
