from __future__ import annotations

import pytest

from live_meeting_transcriber.application.container import ProviderSelectionError, build_diarization_provider
from live_meeting_transcriber.config.settings import Settings
from live_meeting_transcriber.diarization.noop import NoopDiarizationProvider


def test_build_diarization_noop_when_disabled(tmp_path) -> None:
    s = Settings(
        OPENAI_API_KEY="x",
        DATABASE_URL=f"sqlite:////{tmp_path}/db.sqlite3",
        DIARIZATION_ENABLED=False,
        DIARIZATION_PROVIDER="pyannote",
    )
    p = build_diarization_provider(s)
    assert isinstance(p, NoopDiarizationProvider)


def test_build_diarization_noop_explicit(tmp_path) -> None:
    s = Settings(
        OPENAI_API_KEY="x",
        DATABASE_URL=f"sqlite:////{tmp_path}/db.sqlite3",
        DIARIZATION_ENABLED=True,
        DIARIZATION_PROVIDER="noop",
    )
    p = build_diarization_provider(s)
    assert isinstance(p, NoopDiarizationProvider)


def test_build_diarization_pyannote_requires_token(tmp_path) -> None:
    s = Settings(
        OPENAI_API_KEY="x",
        DATABASE_URL=f"sqlite:////{tmp_path}/db.sqlite3",
        DIARIZATION_ENABLED=True,
        DIARIZATION_PROVIDER="pyannote",
        HF_TOKEN=None,
    )
    with pytest.raises(ProviderSelectionError, match="HF_TOKEN"):
        build_diarization_provider(s)


def test_pyannote_provider_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def _fake(name: str, globals=None, locals=None, fromlist=(), level: int = 0):  # type: ignore[no-untyped-def]
        if name == "pyannote" or name.startswith("pyannote."):
            raise ImportError("simulated missing pyannote")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _fake)
    from live_meeting_transcriber.diarization.pyannote_provider import PyannoteDiarizationProvider

    prov = PyannoteDiarizationProvider(hf_token="t", model_id="m")
    with pytest.raises(RuntimeError, match="pyannote"):
        prov._ensure_pipeline()
