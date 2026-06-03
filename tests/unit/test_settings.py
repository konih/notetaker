from __future__ import annotations

from live_meeting_transcriber.config.settings import Settings, load_settings


def test_settings_load_from_env(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("TRANSCRIPTION_PROVIDER", "openai")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("TRANSCRIPTION_MODEL", "test-transcribe-model")
    monkeypatch.setenv("SUMMARY_MODEL", "test-summary-model")
    monkeypatch.setenv("DATABASE_URL", "sqlite:////tmp/live_meeting_transcriber_test.db")
    monkeypatch.setenv("AUDIO_CHUNK_SECONDS", "12")
    monkeypatch.setenv("AUDIO_SAMPLE_RATE", "16000")
    monkeypatch.setenv("AUDIO_CHANNELS", "1")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("KEEP_AUDIO_CHUNKS", "1")

    s = load_settings()
    assert s.openai_api_key == "test-key"
    assert s.transcription_provider == "openai"
    assert s.llm_provider == "openai"
    assert s.transcription_model == "test-transcribe-model"
    assert s.summary_model == "test-summary-model"
    assert s.database_url.startswith("sqlite:")
    assert s.audio_chunk_seconds == 12
    assert s.audio_sample_rate == 16000
    assert s.audio_channels == 1
    assert s.log_level == "DEBUG"
    assert s.keep_audio_chunks is True


def test_log_level_stripped_from_env(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("LOG_LEVEL", "  debug  ")
    monkeypatch.setenv("DATABASE_URL", "sqlite:////tmp/t.db")
    s = load_settings()
    assert s.log_level == "debug"


def test_effective_transcription_model_display() -> None:
    openai_s = Settings.model_construct(
        transcription_provider="openai",
        transcription_model="gpt-4o-mini-transcribe",
        faster_whisper_model="small",
    )
    assert openai_s.effective_transcription_model_display() == "gpt-4o-mini-transcribe"

    fw_s = Settings.model_construct(
        transcription_provider="faster_whisper",
        transcription_model="gpt-4o-mini-transcribe",
        faster_whisper_model="base",
    )
    assert fw_s.effective_transcription_model_display() == "base"
