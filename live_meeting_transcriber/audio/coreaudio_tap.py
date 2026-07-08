"""macOS system-audio capture via Core Audio process taps — the BlackHole-free path.

``ffmpeg -f avfoundation`` can only see *input* devices, so capturing system *output* on
macOS otherwise requires a third-party loopback driver (BlackHole/Loopback/Soundflower).
This adapter instead drives a tiny bundled Swift helper (``native/macos/systemaudiotap.swift``)
that uses Core Audio process taps (macOS 14.4+) to capture system output with no driver, then
hands the raw PCM to ffmpeg to produce the per-chunk WAV the ``AudioCapture`` port expects.

The helper is compiled on demand with ``swiftc`` and ad-hoc code-signed (both required for the
"System Audio Recording Only" TCC prompt to fire). A normal ``:N`` avfoundation device is passed
straight through to :class:`FfmpegAvfoundationCapture`, so the existing BlackHole path keeps
working as a fallback.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from uuid import UUID, uuid4

from live_meeting_transcriber.audio.capture import AudioCaptureError, FfmpegAvfoundationCapture
from live_meeting_transcriber.domain.models import AudioChunk
from live_meeting_transcriber.domain.ports import AudioCapture
from live_meeting_transcriber.utils.time import utc_now

# Sentinel "source" that routes capture through the Core Audio tap instead of an avfoundation
# device index. Chosen so it never collides with ffmpeg's ``:N`` device specifiers.
COREAUDIO_TAP_SOURCE = "coreaudio_tap"
COREAUDIO_TAP_DESCRIPTION = "System Audio (Core Audio tap — no BlackHole needed)"

_HELPER_NAME = "systemaudiotap"
_NATIVE_DIR = Path(__file__).resolve().parents[2] / "native" / "macos"


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=True, capture_output=True, text=True)


def _popen(cmd: list[str]) -> subprocess.Popen[bytes]:
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def default_cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME")
    root = Path(base) if base else Path.home() / ".cache"
    return root / "live-meeting-transcriber"


def build_helper(*, source_dir: Path = _NATIVE_DIR, cache_dir: Path | None = None) -> Path:
    """Compile + ad-hoc sign the Swift tap helper, caching the binary. Returns its path.

    Rebuilds only when the cached binary is older than the Swift source or Info.plist. Raises
    :class:`AudioCaptureError` if ``swiftc`` is unavailable (e.g. Xcode CLT not installed).
    """
    if shutil.which("swiftc") is None:
        raise AudioCaptureError(
            "swiftc not found; install the Xcode command line tools (xcode-select --install) "
            "to build the macOS system-audio helper, or install BlackHole and set "
            "AUDIO_MACOS_SYSTEM_CAPTURE=avfoundation"
        )
    cache_dir = cache_dir or default_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    binary = cache_dir / _HELPER_NAME
    swift_src = source_dir / f"{_HELPER_NAME}.swift"
    info_plist = source_dir / "Info.plist"

    newest_src = max(swift_src.stat().st_mtime, info_plist.stat().st_mtime)
    if binary.exists() and binary.stat().st_mtime >= newest_src:
        return binary

    # Embed Info.plist (NSAudioCaptureUsageDescription) into the binary so the TCC prompt fires.
    _run(
        [
            "swiftc",
            str(swift_src),
            "-O",
            "-o",
            str(binary),
            "-Xlinker",
            "-sectcreate",
            "-Xlinker",
            "__TEXT",
            "-Xlinker",
            "__info_plist",
            "-Xlinker",
            str(info_plist),
        ]
    )
    _run(["codesign", "-s", "-", "--force", str(binary)])
    return binary


def _parse_tap_format(stderr: str) -> tuple[int, int, bool]:
    """Parse the helper's ``rate=<hz> ch=<n> float=<0|1>`` line; default 48k/stereo/float."""
    rate, channels, is_float = 48000, 2, True
    for token in stderr.split():
        key, _, value = token.partition("=")
        if not value:
            continue
        try:
            if key == "rate":
                rate = int(float(value))
            elif key == "ch":
                channels = int(value)
            elif key == "float":
                is_float = value != "0"
        except ValueError:
            continue
    return rate, channels, is_float


def _decode_stderr(raw: bytes | str | None) -> str:
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", "replace")
    return raw


class MacosAudioCapture(AudioCapture):
    """AudioCapture that taps system audio natively, delegating device captures to ffmpeg."""

    def __init__(
        self,
        *,
        avfoundation: AudioCapture | None = None,
        helper_path: Path | None = None,
        helper_builder: Callable[[], Path] | None = None,
    ) -> None:
        self._avf = avfoundation or FfmpegAvfoundationCapture()
        self._helper_path = helper_path
        self._helper_builder = helper_builder or build_helper

    def _helper(self) -> Path:
        if self._helper_path is not None:
            return self._helper_path
        return self._helper_builder()

    def capture_chunk(
        self,
        *,
        session_id: UUID,
        source: str,
        microphone_source: str | None = None,
        chunk_seconds: int,
        sample_rate_hz: int,
        channels: int,
        output_dir: Path,
    ) -> AudioChunk:
        if source != COREAUDIO_TAP_SOURCE:
            # Normal avfoundation device (incl. a BlackHole loopback) → existing ffmpeg path.
            return self._avf.capture_chunk(
                session_id=session_id,
                source=source,
                microphone_source=microphone_source,
                chunk_seconds=chunk_seconds,
                sample_rate_hz=sample_rate_hz,
                channels=channels,
                output_dir=output_dir,
            )

        output_dir.mkdir(parents=True, exist_ok=True)
        chunk_id = uuid4()
        started_at = utc_now()
        out_path = output_dir / f"{chunk_id}.wav"
        raw_path = output_dir / f"{chunk_id}.raw.f32"
        mic = microphone_source if microphone_source and microphone_source != source else None

        try:
            helper = self._helper()
            if mic is None:
                stderr = self._capture_system(helper, raw_path, chunk_seconds)
                self._raw_to_wav(
                    raw_path,
                    out_path,
                    stderr=stderr,
                    chunk_seconds=chunk_seconds,
                    sample_rate_hz=sample_rate_hz,
                    channels=channels,
                )
            else:
                mic_path = output_dir / f"{chunk_id}.mic.wav"
                stderr = self._capture_system_and_mic(
                    helper, raw_path, mic_path, mic, chunk_seconds, sample_rate_hz
                )
                self._combine(
                    raw_path,
                    mic_path,
                    out_path,
                    stderr=stderr,
                    chunk_seconds=chunk_seconds,
                    sample_rate_hz=sample_rate_hz,
                    channels=channels,
                )
                mic_path.unlink(missing_ok=True)
        except FileNotFoundError as e:
            raise AudioCaptureError("ffmpeg not found; install ffmpeg") from e
        except subprocess.CalledProcessError as e:
            detail = _decode_stderr(e.stderr).strip()
            raise AudioCaptureError(f"system-audio capture failed: {detail}") from e
        finally:
            raw_path.unlink(missing_ok=True)

        ended_at = utc_now()
        return AudioChunk(
            id=chunk_id,
            session_id=session_id,
            started_at=started_at,
            ended_at=ended_at,
            path=out_path,
            sample_rate_hz=sample_rate_hz,
            channels=channels,
        )

    # -- capture steps -------------------------------------------------------

    def _capture_system(self, helper: Path, raw_path: Path, chunk_seconds: int) -> str:
        proc = _run([str(helper), "--out", str(raw_path), "--seconds", str(chunk_seconds)])
        return proc.stderr or ""

    def _capture_system_and_mic(
        self,
        helper: Path,
        raw_path: Path,
        mic_path: Path,
        mic: str,
        chunk_seconds: int,
        sample_rate_hz: int,
    ) -> str:
        # Start both captures together so system + mic cover the same wall-clock window.
        tap_proc = _popen([str(helper), "--out", str(raw_path), "--seconds", str(chunk_seconds)])
        mic_proc = _popen(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "avfoundation",
                "-thread_queue_size",
                "4096",
                "-i",
                mic,
                "-t",
                str(chunk_seconds),
                "-ac",
                "1",
                "-ar",
                str(sample_rate_hz),
                "-acodec",
                "pcm_s16le",
                str(mic_path),
            ]
        )
        timeout = chunk_seconds + 15
        _, tap_err = tap_proc.communicate(timeout=timeout)
        mic_proc.communicate(timeout=timeout)
        return _decode_stderr(tap_err)

    # -- ffmpeg finalize -----------------------------------------------------

    def _tap_input_args(self, raw_path: Path, stderr: str) -> list[str]:
        rate, channels, is_float = _parse_tap_format(stderr)
        fmt = "f32le" if is_float else "s16le"
        return ["-f", fmt, "-ar", str(rate), "-ac", str(channels), "-i", str(raw_path)]

    def _silent_input_args(self, sample_rate_hz: int) -> list[str]:
        return ["-f", "lavfi", "-i", f"anullsrc=r={sample_rate_hz}:cl=stereo"]

    def _raw_to_wav(
        self,
        raw_path: Path,
        out_path: Path,
        *,
        stderr: str,
        chunk_seconds: int,
        sample_rate_hz: int,
        channels: int,
    ) -> None:
        layout = "mono" if channels == 1 else "stereo"
        if not raw_path.exists() or raw_path.stat().st_size == 0:
            # Pure silence during the window → emit a silent chunk of the right length so the
            # recorder timeline stays aligned.
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"anullsrc=r={sample_rate_hz}:cl={layout}",
                "-t",
                str(chunk_seconds),
                "-ac",
                str(channels),
                "-ar",
                str(sample_rate_hz),
                "-acodec",
                "pcm_s16le",
                str(out_path),
            ]
        else:
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                *self._tap_input_args(raw_path, stderr),
                "-ac",
                str(channels),
                "-ar",
                str(sample_rate_hz),
                "-acodec",
                "pcm_s16le",
                str(out_path),
            ]
        _run(cmd)

    def _combine(
        self,
        raw_path: Path,
        mic_path: Path,
        out_path: Path,
        *,
        stderr: str,
        chunk_seconds: int,
        sample_rate_hz: int,
        channels: int,
    ) -> None:
        has_system = raw_path.exists() and raw_path.stat().st_size > 0
        system_input = (
            self._tap_input_args(raw_path, stderr)
            if has_system
            else self._silent_input_args(sample_rate_hz)
        )
        if channels >= 2:
            # Stereo dual-path: left = microphone (local), right = system (remote).
            filter_complex = (
                "[0:a]aresample=async=1,pan=mono|c0=c0[sys];"
                "[1:a]aresample=async=1,pan=mono|c0=c0[mic];"
                "[mic][sys]join=inputs=2:channel_layout=stereo[aout]"
            )
        else:
            filter_complex = (
                "[0:a]aresample=async=1[a0];[1:a]aresample=async=1[a1];"
                "[a0][a1]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0[aout]"
            )
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            *system_input,
            "-i",
            str(mic_path),
            "-filter_complex",
            filter_complex,
            "-map",
            "[aout]",
            "-t",
            str(chunk_seconds),
            "-ac",
            str(channels),
            "-ar",
            str(sample_rate_hz),
            "-acodec",
            "pcm_s16le",
            str(out_path),
        ]
        _run(cmd)
