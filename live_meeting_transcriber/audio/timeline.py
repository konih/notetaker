"""Map concatenated session audio time (seconds from session WAV start) to wall-clock datetimes."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from live_meeting_transcriber.domain.session_audio import (
    AudioTimelineEntry,
    map_audio_time_to_wall,
)

__all__ = [
    "AudioTimelineEntry",
    "append_timeline_entry",
    "load_timeline",
    "map_audio_time_to_wall",
    "timeline_file",
]


def timeline_file(session_audio_root: Path) -> Path:
    return session_audio_root / "session_audio_timeline.jsonl"


def append_timeline_entry(session_audio_root: Path, entry: AudioTimelineEntry) -> None:
    session_audio_root.mkdir(parents=True, exist_ok=True)
    path = timeline_file(session_audio_root)
    payload = {
        "audio_start_sec": entry.audio_start_sec,
        "audio_end_sec": entry.audio_end_sec,
        "wall_started_at": entry.wall_started_at.isoformat(),
        "wall_ended_at": entry.wall_ended_at.isoformat(),
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def load_timeline(session_audio_root: Path) -> list[AudioTimelineEntry]:
    path = timeline_file(session_audio_root)
    if not path.is_file():
        return []
    out: list[AudioTimelineEntry] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        raw = json.loads(line)
        out.append(
            AudioTimelineEntry(
                audio_start_sec=float(raw["audio_start_sec"]),
                audio_end_sec=float(raw["audio_end_sec"]),
                wall_started_at=datetime.fromisoformat(str(raw["wall_started_at"])),
                wall_ended_at=datetime.fromisoformat(str(raw["wall_ended_at"])),
            )
        )
    return out
