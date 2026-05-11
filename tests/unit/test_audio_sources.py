from __future__ import annotations

from dataclasses import dataclass

from live_meeting_transcriber.audio.sources import resolve_microphone_source
from live_meeting_transcriber.config.settings import Settings


@dataclass(frozen=True)
class _Dev:
    mic: str | None = "default-mic"

    def get_default_microphone_source(self) -> str | None:
        return self.mic


def test_resolve_microphone_disabled_in_settings(monkeypatch) -> None:
    monkeypatch.setenv("AUDIO_INCLUDE_MICROPHONE", "false")
    s = Settings(
        OPENAI_API_KEY="x",
        DATABASE_URL="sqlite:////tmp/t.db",
    )
    assert resolve_microphone_source(s, _Dev()) is None


def test_resolve_microphone_cli_no_mic() -> None:
    s = Settings(OPENAI_API_KEY="x", DATABASE_URL="sqlite:////tmp/t.db", AUDIO_INCLUDE_MICROPHONE=True)
    assert resolve_microphone_source(s, _Dev(), cli_no_microphone=True) is None


def test_resolve_microphone_explicit_cli() -> None:
    s = Settings(OPENAI_API_KEY="x", DATABASE_URL="sqlite:////tmp/t.db", AUDIO_INCLUDE_MICROPHONE=True)
    assert resolve_microphone_source(s, _Dev(mic=None), cli_explicit="  my-mic  ") == "my-mic"
