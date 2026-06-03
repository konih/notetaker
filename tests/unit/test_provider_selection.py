from __future__ import annotations

import pytest
from live_meeting_transcriber.application.container import ProviderSelectionError, build_container
from live_meeting_transcriber.config.settings import Settings
from live_meeting_transcriber.domain.ports import SummarizationProvider, TranscriptionProvider


def test_provider_selection_requires_key(tmp_path) -> None:
    s = Settings(
        OPENAI_API_KEY=None,
        DATABASE_URL=f"sqlite:////{tmp_path}/db.sqlite3",
    )
    with pytest.raises(ProviderSelectionError):
        build_container(s)


def test_openai_providers_behind_ports(tmp_path) -> None:
    s = Settings(
        OPENAI_API_KEY="test-key",
        DATABASE_URL=f"sqlite:////{tmp_path}/db.sqlite3",
    )
    c = build_container(s)
    try:
        assert isinstance(c.transcriber, TranscriptionProvider)
        assert isinstance(c.summarizer, SummarizationProvider)
    finally:
        c.close()


def test_faster_whisper_transcription_still_needs_openai_key_for_summaries(tmp_path) -> None:
    s = Settings(
        OPENAI_API_KEY=None,
        transcription_provider="faster_whisper",
        DATABASE_URL=f"sqlite:////{tmp_path}/db.sqlite3",
    )
    with pytest.raises(ProviderSelectionError):
        build_container(s)


def test_faster_whisper_transcription_builds_with_openai_summaries(tmp_path) -> None:
    from live_meeting_transcriber.transcription.faster_whisper_transcriber import (
        FasterWhisperTranscriptionProvider,
    )

    s = Settings(
        OPENAI_API_KEY="k",
        transcription_provider="faster_whisper",
        DATABASE_URL=f"sqlite:////{tmp_path}/db.sqlite3",
    )
    c = build_container(s)
    try:
        assert isinstance(c.transcriber, FasterWhisperTranscriptionProvider)
    finally:
        c.close()
