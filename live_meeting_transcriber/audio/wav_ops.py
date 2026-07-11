"""Concrete :class:`~live_meeting_transcriber.domain.ports.WavAudioOps` (ffmpeg + stdlib wave)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from live_meeting_transcriber.audio.stereo import extract_mono_channel_wav, rms_mixdown_to_mono_wav
from live_meeting_transcriber.audio.wav_level import (
    peak_linear_from_wav_path,
    rms_dbfs_from_wav_path,
)
from live_meeting_transcriber.audio.wav_segment import (
    extract_wav_time_range,
    safe_wav_duration_seconds,
    wav_is_transcribable,
)


@dataclass(frozen=True)
class FfmpegWavOps:
    """WAV inspection/transform helpers behind the ``WavAudioOps`` port."""

    def peak_linear(self, path: Path) -> float:
        return peak_linear_from_wav_path(path)

    def rms_dbfs(self, path: Path) -> float:
        return rms_dbfs_from_wav_path(path)

    def duration_seconds(self, path: Path) -> float:
        return safe_wav_duration_seconds(path)

    def is_transcribable(self, path: Path) -> bool:
        return wav_is_transcribable(path)

    def mixdown_to_mono(self, path: Path, *, sample_rate_hz: int) -> Path:
        return rms_mixdown_to_mono_wav(path, sample_rate_hz=sample_rate_hz)

    def extract_mono_channel(self, path: Path, channel: int, *, sample_rate_hz: int) -> Path:
        return extract_mono_channel_wav(path, channel, sample_rate_hz=sample_rate_hz)

    def extract_time_range(
        self,
        *,
        src: Path,
        dest: Path,
        start_seconds: float,
        end_seconds: float,
        sample_rate_hz: int,
        channels: int,
    ) -> None:
        extract_wav_time_range(
            src=src,
            dest=dest,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            sample_rate_hz=sample_rate_hz,
            channels=channels,
        )
