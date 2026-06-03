"""Map concatenated session audio time (seconds from session WAV start) to wall-clock datetimes."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path


@dataclass(frozen=True)
class AudioTimelineEntry:
    """One appended chunk: audio interval in the rolling ``full_session.wav`` and its wall-clock span."""

    audio_start_sec: float
    audio_end_sec: float
    wall_started_at: datetime
    wall_ended_at: datetime


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


def map_audio_time_to_wall(entries: Sequence[AudioTimelineEntry], t_sec: float) -> datetime:
    """Linearly map a position in the concatenated WAV timeline to wall time."""
    if not entries:
        raise ValueError("timeline is empty")
    if t_sec <= entries[0].audio_start_sec:
        return entries[0].wall_started_at
    if t_sec >= entries[-1].audio_end_sec:
        return entries[-1].wall_ended_at
    for e in entries:
        if t_sec < e.audio_end_sec - 1e-9:
            dur_a = e.audio_end_sec - e.audio_start_sec
            if dur_a <= 1e-9:
                return e.wall_started_at
            frac = (t_sec - e.audio_start_sec) / dur_a
            frac = max(0.0, min(1.0, frac))
            wall_delta = (e.wall_ended_at - e.wall_started_at).total_seconds() * frac
            return e.wall_started_at + timedelta(seconds=wall_delta)
    return entries[-1].wall_ended_at
