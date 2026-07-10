"""Append per-chunk WAV captures into one long ``full_session.wav`` per meeting."""

from __future__ import annotations

import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from live_meeting_transcriber.audio.timeline import AudioTimelineEntry, append_timeline_entry
from live_meeting_transcriber.audio.wav_segment import safe_wav_duration_seconds


class SessionAudioAppendError(RuntimeError):
    pass


def session_audio_dir(data_dir: Path, session_id: UUID) -> Path:
    d = (data_dir / "sessions" / str(session_id)).resolve()
    d.mkdir(parents=True, exist_ok=True)
    return d


def full_session_wav_path(session_audio_root: Path) -> Path:
    return session_audio_root / "full_session.wav"


def append_chunk_to_full_session_wav(
    *,
    session_audio_root: Path,
    chunk_wav: Path,
    sample_rate_hz: int,
) -> Path:
    """Concatenate ``chunk_wav`` onto the rolling full-session file (same layout / rate as chunks)."""
    session_audio_root.mkdir(parents=True, exist_ok=True)
    dest = full_session_wav_path(session_audio_root)
    if not chunk_wav.is_file():
        raise SessionAudioAppendError(f"chunk WAV missing: {chunk_wav}")

    if not dest.exists():
        shutil.copy2(chunk_wav, dest)
        return dest

    # Must end in ``.wav`` (or pass ``-f wav``): ``full_session.wav.next`` makes ffmpeg
    # unable to infer the output muxer on some builds.
    out_tmp = session_audio_root / "full_session.tmp.wav"
    try:
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(dest),
            "-i",
            str(chunk_wav),
            "-filter_complex",
            "[0:a][1:a]concat=n=2:v=0:a=1[aout]",
            "-map",
            "[aout]",
            "-ar",
            str(sample_rate_hz),
            "-acodec",
            "pcm_s16le",
            "-f",
            "wav",
            str(out_tmp),
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError as e:
        raise SessionAudioAppendError("ffmpeg not found; install ffmpeg") from e
    except subprocess.CalledProcessError as e:
        raise SessionAudioAppendError(
            f"ffmpeg concat failed: {(e.stderr or '').strip() or e}"
        ) from e

    out_tmp.replace(dest)
    return dest


def append_chunk_with_timeline(
    *,
    session_audio_root: Path,
    chunk_wav: Path,
    sample_rate_hz: int,
    wall_started_at: datetime,
    wall_ended_at: datetime,
    fallback_duration_seconds: float,
    log: Any,
) -> None:
    """Append one chunk WAV onto ``full_session.wav`` and record its timeline entry as one
    logical operation.

    The timeline entry is written **only** if the audio append succeeds, so a failure
    partway through never diverges audio/timeline state (ARCH-16). A failed append is
    logged and swallowed — the meeting keeps recording so it can still be finalized
    offline from whatever audio did persist.
    """
    file_dur = safe_wav_duration_seconds(chunk_wav)
    if file_dur <= 0.0:
        file_dur = fallback_duration_seconds

    audio_start = safe_wav_duration_seconds(full_session_wav_path(session_audio_root))
    audio_end = audio_start + file_dur
    try:
        append_chunk_to_full_session_wav(
            session_audio_root=session_audio_root,
            chunk_wav=chunk_wav,
            sample_rate_hz=sample_rate_hz,
        )
    except Exception as e:
        log.warning("session_full_audio_append_failed", error=str(e))
        return
    append_timeline_entry(
        session_audio_root,
        AudioTimelineEntry(
            audio_start_sec=audio_start,
            audio_end_sec=audio_end,
            wall_started_at=wall_started_at,
            wall_ended_at=wall_ended_at,
        ),
    )
