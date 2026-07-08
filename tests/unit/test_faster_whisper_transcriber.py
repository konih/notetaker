from __future__ import annotations

import sys
from datetime import datetime, timedelta
from types import ModuleType
from uuid import uuid4

import pytest
from live_meeting_transcriber.domain.exceptions import EmptyTranscriptionError
from live_meeting_transcriber.domain.models import AudioChunk
from live_meeting_transcriber.transcription.faster_whisper_transcriber import (
    FasterWhisperTranscriptionError,
    FasterWhisperTranscriptionProvider,
)


@pytest.mark.asyncio
async def test_faster_whisper_transcribe_joins_segments(tmp_path) -> None:
    wav = tmp_path / "chunk.wav"
    wav.write_bytes(b"")

    real = sys.modules.pop("faster_whisper", None)
    try:
        m = ModuleType("faster_whisper")

        class WhisperModel:
            def __init__(self, model_size: str, device: str, compute_type: str) -> None:
                self._size = model_size
                self._device = device
                self._compute_type = compute_type

            def transcribe(self, path: str, **kwargs: object):
                assert path == str(wav)
                assert kwargs.get("vad_filter") is True

                class Seg:
                    def __init__(self, text: str) -> None:
                        self.text = text

                class Info:
                    language = "en"

                def gen():
                    yield Seg("Hello")
                    yield Seg("there")

                return gen(), Info()

        m.WhisperModel = WhisperModel
        sys.modules["faster_whisper"] = m

        prov = FasterWhisperTranscriptionProvider(
            model_size="tiny",
            device="cpu",
            compute_type="int8",
            language="en",
        )
        sid = uuid4()
        t0 = datetime(2026, 1, 1, 12, 0, 0)
        chunk = AudioChunk(
            session_id=sid,
            started_at=t0,
            ended_at=t0 + timedelta(seconds=2),
            path=wav,
            sample_rate_hz=16000,
            channels=1,
        )
        seg = await prov.transcribe(chunk=chunk)
        assert seg.text == "Hello there"
        assert seg.metadata.provider == "faster_whisper"
        assert seg.metadata.model == "tiny"
        assert seg.metadata.extra.get("language") == "en"
    finally:
        if real is not None:
            sys.modules["faster_whisper"] = real
        else:
            sys.modules.pop("faster_whisper", None)


@pytest.mark.asyncio
async def test_faster_whisper_empty_raises(tmp_path) -> None:
    wav = tmp_path / "chunk.wav"
    wav.write_bytes(b"")

    real = sys.modules.pop("faster_whisper", None)
    try:
        m = ModuleType("faster_whisper")

        class WhisperModel:
            def __init__(self, *a: object, **k: object) -> None:
                pass

            def transcribe(self, path: str, **kwargs: object):
                class Info:
                    language = None

                return iter(()), Info()

        m.WhisperModel = WhisperModel
        sys.modules["faster_whisper"] = m

        prov = FasterWhisperTranscriptionProvider(
            model_size="tiny",
            device="cpu",
            compute_type="int8",
            language=None,
        )
        sid = uuid4()
        t0 = datetime(2026, 1, 1, 12, 0, 0)
        chunk = AudioChunk(
            session_id=sid,
            started_at=t0,
            ended_at=t0 + timedelta(seconds=1),
            path=wav,
            sample_rate_hz=16000,
            channels=1,
        )
        with pytest.raises(EmptyTranscriptionError):
            await prov.transcribe(chunk=chunk)
    finally:
        if real is not None:
            sys.modules["faster_whisper"] = real
        else:
            sys.modules.pop("faster_whisper", None)


@pytest.mark.asyncio
async def test_faster_whisper_runtime_error_when_package_missing(tmp_path, monkeypatch) -> None:
    wav = tmp_path / "chunk.wav"
    wav.write_bytes(b"")

    real = sys.modules.pop("faster_whisper", None)
    try:

        def boom(name: str, *a: object, **k: object):
            if name == "faster_whisper":
                raise ImportError("no package")
            return real_import(name, *a, **k)

        import builtins

        real_import = builtins.__import__
        monkeypatch.setattr(builtins, "__import__", boom)

        prov = FasterWhisperTranscriptionProvider(
            model_size="tiny",
            device="cpu",
            compute_type="int8",
            language=None,
        )
        sid = uuid4()
        t0 = datetime(2026, 1, 1, 12, 0, 0)
        chunk = AudioChunk(
            session_id=sid,
            started_at=t0,
            ended_at=t0 + timedelta(seconds=1),
            path=wav,
            sample_rate_hz=16000,
            channels=1,
        )
        with pytest.raises(RuntimeError, match="faster-whisper is not installed"):
            await prov.transcribe(chunk=chunk)
    finally:
        if real is not None:
            sys.modules["faster_whisper"] = real


@pytest.mark.asyncio
async def test_faster_whisper_maps_model_errors(tmp_path) -> None:
    wav = tmp_path / "chunk.wav"
    wav.write_bytes(b"")

    real = sys.modules.pop("faster_whisper", None)
    try:
        m = ModuleType("faster_whisper")

        class WhisperModel:
            def __init__(self, *a: object, **k: object) -> None:
                pass

            def transcribe(self, path: str, **kwargs: object):
                raise ValueError("bad audio")

        m.WhisperModel = WhisperModel
        sys.modules["faster_whisper"] = m

        prov = FasterWhisperTranscriptionProvider(
            model_size="tiny",
            device="cpu",
            compute_type="int8",
            language=None,
        )
        sid = uuid4()
        t0 = datetime(2026, 1, 1, 12, 0, 0)
        chunk = AudioChunk(
            session_id=sid,
            started_at=t0,
            ended_at=t0 + timedelta(seconds=1),
            path=wav,
            sample_rate_hz=16000,
            channels=1,
        )
        with pytest.raises(FasterWhisperTranscriptionError, match="bad audio"):
            await prov.transcribe(chunk=chunk)
    finally:
        if real is not None:
            sys.modules["faster_whisper"] = real
        else:
            sys.modules.pop("faster_whisper", None)


@pytest.mark.asyncio
async def test_faster_whisper_warm_up_loads_model_once() -> None:
    real = sys.modules.pop("faster_whisper", None)
    try:
        m = ModuleType("faster_whisper")
        loads: list[int] = []

        class WhisperModel:
            def __init__(self, *a: object, **k: object) -> None:
                loads.append(1)

        m.WhisperModel = WhisperModel
        sys.modules["faster_whisper"] = m

        prov = FasterWhisperTranscriptionProvider(
            model_size="tiny", device="cpu", compute_type="int8", language=None
        )
        await prov.warm_up()
        await prov.warm_up()
        assert len(loads) == 1  # model cached after first load
    finally:
        if real is not None:
            sys.modules["faster_whisper"] = real
        else:
            sys.modules.pop("faster_whisper", None)


@pytest.mark.asyncio
async def test_faster_whisper_warm_up_wraps_load_failure() -> None:
    real = sys.modules.pop("faster_whisper", None)
    try:
        m = ModuleType("faster_whisper")

        class WhisperModel:
            def __init__(self, *a: object, **k: object) -> None:
                raise ValueError("bad value(s) in fds_to_keep")

        m.WhisperModel = WhisperModel
        sys.modules["faster_whisper"] = m

        prov = FasterWhisperTranscriptionProvider(
            model_size="tiny", device="cpu", compute_type="int8", language=None
        )
        with pytest.raises(FasterWhisperTranscriptionError, match="fds_to_keep"):
            await prov.warm_up()
    finally:
        if real is not None:
            sys.modules["faster_whisper"] = real
        else:
            sys.modules.pop("faster_whisper", None)
