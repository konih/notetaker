from __future__ import annotations

from pathlib import Path

import pytest
from live_meeting_transcriber.application.container import ProviderSelectionError, build_container
from live_meeting_transcriber.config.settings import Settings
from live_meeting_transcriber.domain.ports import SummarizationProvider, TranscriptionProvider


def test_provider_selection_requires_key_for_openai_transcription(tmp_path: Path) -> None:
    s = Settings(
        openai_api_key=None,
        transcription_provider="openai",
        database_url=f"sqlite:////{tmp_path}/db.sqlite3",
    )
    with pytest.raises(ProviderSelectionError, match="OPENAI_API_KEY"):
        build_container(s)


def test_missing_openai_key_error_offers_keyless_alternative(tmp_path: Path) -> None:
    """The error must be actionable: name the keyless faster_whisper fallback (F3)."""
    s = Settings(
        openai_api_key=None,
        transcription_provider="openai",
        database_url=f"sqlite:////{tmp_path}/db.sqlite3",
    )
    with pytest.raises(ProviderSelectionError, match="faster_whisper"):
        build_container(s)


def test_faster_whisper_starts_without_openai_key(tmp_path: Path) -> None:
    from live_meeting_transcriber.summarization.unavailable import (
        UnavailableSummarizationProvider,
    )
    from live_meeting_transcriber.transcription.faster_whisper_transcriber import (
        FasterWhisperTranscriptionProvider,
    )

    s = Settings(
        openai_api_key=None,
        transcription_provider="faster_whisper",
        database_url=f"sqlite:////{tmp_path}/db.sqlite3",
    )
    c = build_container(s)
    try:
        assert isinstance(c.transcriber, FasterWhisperTranscriptionProvider)
        assert isinstance(c.summarizer, UnavailableSummarizationProvider)
    finally:
        c.close()


def test_openai_providers_behind_ports(tmp_path: Path) -> None:
    s = Settings(
        openai_api_key="test-key",
        database_url=f"sqlite:////{tmp_path}/db.sqlite3",
    )
    c = build_container(s)
    try:
        assert isinstance(c.transcriber, TranscriptionProvider)
        assert isinstance(c.summarizer, SummarizationProvider)
    finally:
        c.close()


def test_faster_whisper_transcription_builds_with_openai_summaries(tmp_path: Path) -> None:
    from live_meeting_transcriber.transcription.faster_whisper_transcriber import (
        FasterWhisperTranscriptionProvider,
    )

    s = Settings(
        openai_api_key="k",
        transcription_provider="faster_whisper",
        database_url=f"sqlite:////{tmp_path}/db.sqlite3",
    )
    c = build_container(s)
    try:
        assert isinstance(c.transcriber, FasterWhisperTranscriptionProvider)
    finally:
        c.close()
