from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from live_meeting_transcriber.application.container import build_diarization_provider
from live_meeting_transcriber.config.settings import Settings
from live_meeting_transcriber.diarization.pyannote_provider import PyannoteDiarizationProvider
from live_meeting_transcriber.domain.models import AudioChunk
from pydantic import ValidationError


def test_settings_diarization_min_gt_max_raises(tmp_path) -> None:
    with pytest.raises(ValidationError):
        Settings(
            OPENAI_API_KEY="x",
            DATABASE_URL=f"sqlite:////{tmp_path}/db.sqlite3",
            DIARIZATION_MIN_SPEAKERS=3,
            DIARIZATION_MAX_SPEAKERS=2,
        )


def test_pyannote_pipeline_kwargs_num_only_when_set(tmp_path) -> None:
    s = Settings(
        OPENAI_API_KEY="x",
        DATABASE_URL=f"sqlite:////{tmp_path}/db.sqlite3",
        DIARIZATION_NUM_SPEAKERS=2,
        DIARIZATION_MIN_SPEAKERS=2,
        DIARIZATION_MAX_SPEAKERS=4,
    )
    assert s.pyannote_diarization_pipeline_kwargs() == {"num_speakers": 2}


def test_pyannote_pipeline_kwargs_min_max(tmp_path) -> None:
    s = Settings(
        OPENAI_API_KEY="x",
        DATABASE_URL=f"sqlite:////{tmp_path}/db.sqlite3",
        DIARIZATION_MIN_SPEAKERS=2,
        DIARIZATION_MAX_SPEAKERS=4,
    )
    assert s.pyannote_diarization_pipeline_kwargs() == {
        "min_speakers": 2,
        "max_speakers": 4,
    }


def test_build_pyannote_passes_pipeline_kwargs(tmp_path) -> None:
    s = Settings(
        OPENAI_API_KEY="x",
        DATABASE_URL=f"sqlite:////{tmp_path}/db.sqlite3",
        DIARIZATION_ENABLED=True,
        DIARIZATION_PROVIDER="pyannote",
        HF_TOKEN="t",
        DIARIZATION_NUM_SPEAKERS=2,
    )
    p = build_diarization_provider(s)
    assert isinstance(p, PyannoteDiarizationProvider)
    assert p._pipeline_call_kw == {"num_speakers": 2}


def test_pyannote_run_sync_typeerror_falls_back_without_kwargs(tmp_path) -> None:
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    chunk = AudioChunk(
        session_id=uuid4(),
        started_at=now,
        ended_at=now + timedelta(seconds=1),
        path=Path(tmp_path) / "x.wav",
        sample_rate_hz=16000,
        channels=1,
    )

    class _Ann:
        def itertracks(self, yield_label: bool = False):
            return iter([])

    calls: list[tuple[str, dict[str, int]]] = []

    class _Pipe:
        def __call__(self, path: str, **kw: int) -> _Ann:
            calls.append((path, dict(kw)))
            if kw:
                raise TypeError("simulated old API")
            return _Ann()

    prov = PyannoteDiarizationProvider(
        hf_token="t",
        model_id="m",
        pipeline_call_kw={"num_speakers": 2},
    )
    prov._pipeline = _Pipe()
    prov._run_sync(chunk)
    assert len(calls) == 2
    assert calls[0] == (str(chunk.path), {"num_speakers": 2})
    assert calls[1] == (str(chunk.path), {})
