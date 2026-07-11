"""Characterization pin for the ``Settings`` public contract (A8, ARCH-17).

The per-area split of ``config/settings.py`` is a behavior-preserving refactor.
This inventory freezes the externally observable surface so any accidental drift
(a renamed field, a changed env-var alias, a secret leaking into the YAML store)
fails loudly instead of shipping silently. If a field is *intentionally* added or
removed, update this map in the same commit — that is the review trigger.
"""

from __future__ import annotations

from live_meeting_transcriber.config.settings import (
    SECRET_FIELD_NAMES,
    Settings,
    settings_to_yaml_dict,
)

# Every field name -> env-var alias, exactly as resolved by pydantic-settings.
EXPECTED_FIELD_ALIASES: dict[str, str] = {
    "transcription_provider": "TRANSCRIPTION_PROVIDER",
    "llm_provider": "LLM_PROVIDER",
    "openai_api_key": "OPENAI_API_KEY",
    "transcription_model": "TRANSCRIPTION_MODEL",
    "summary_model": "SUMMARY_MODEL",
    "faster_whisper_model": "FASTER_WHISPER_MODEL",
    "faster_whisper_device": "FASTER_WHISPER_DEVICE",
    "faster_whisper_compute_type": "FASTER_WHISPER_COMPUTE_TYPE",
    "faster_whisper_language": "FASTER_WHISPER_LANGUAGE",
    "database_url": "DATABASE_URL",
    "audio_chunk_seconds": "AUDIO_CHUNK_SECONDS",
    "audio_sample_rate": "AUDIO_SAMPLE_RATE",
    "audio_channels": "AUDIO_CHANNELS",
    "audio_stereo_mode": "AUDIO_STEREO_MODE",
    "keep_audio_chunks": "KEEP_AUDIO_CHUNKS",
    "audio_silence_skip_enabled": "AUDIO_SILENCE_SKIP_ENABLED",
    "audio_silence_threshold_dbfs": "AUDIO_SILENCE_THRESHOLD_DBFS",
    "audio_include_microphone": "AUDIO_INCLUDE_MICROPHONE",
    "audio_microphone_source": "AUDIO_MICROPHONE_SOURCE",
    "audio_macos_system_capture": "AUDIO_MACOS_SYSTEM_CAPTURE",
    "log_level": "LOG_LEVEL",
    "log_enable_file": "LOG_ENABLE_FILE",
    "log_file": "LOG_FILE",
    "log_file_max_mb": "LOG_FILE_MAX_MB",
    "log_file_backup_count": "LOG_FILE_BACKUP_COUNT",
    "finalize_on_session_stop": "FINALIZE_ON_SESSION_STOP",
    "whisperx_model": "WHISPERX_MODEL",
    "whisperx_device": "WHISPERX_DEVICE",
    "whisperx_torch_device": "WHISPERX_TORCH_DEVICE",
    "whisperx_compute_type": "WHISPERX_COMPUTE_TYPE",
    "whisperx_batch_size": "WHISPERX_BATCH_SIZE",
    "whisperx_language": "WHISPERX_LANGUAGE",
    "whisperx_skip_alignment": "WHISPERX_SKIP_ALIGNMENT",
    "whisperx_diarize_device": "WHISPERX_DIARIZE_DEVICE",
    "diarization_enabled": "DIARIZATION_ENABLED",
    "diarization_provider": "DIARIZATION_PROVIDER",
    "hf_token": "HF_TOKEN",
    "pyannote_model": "PYANNOTE_MODEL",
    "diarization_num_speakers": "DIARIZATION_NUM_SPEAKERS",
    "diarization_min_speakers": "DIARIZATION_MIN_SPEAKERS",
    "diarization_max_speakers": "DIARIZATION_MAX_SPEAKERS",
    "obsidian_people_dir": "OBSIDIAN_PEOPLE_DIR",
    "obsidian_meetings_dir": "OBSIDIAN_MEETINGS_DIR",
    "obsidian_meeting_template": "OBSIDIAN_MEETING_TEMPLATE",
    "obsidian_person_template": "OBSIDIAN_PERSON_TEMPLATE",
    "obsidian_screenshots_dir": "OBSIDIAN_SCREENSHOTS_DIR",
    "screenshots_export_enabled": "SCREENSHOTS_EXPORT_ENABLED",
    "screenshots_source_dir": "SCREENSHOTS_SOURCE_DIR",
    "video_slide_strategy": "VIDEO_SLIDE_STRATEGY",
    "video_slide_sample_interval_seconds": "VIDEO_SLIDE_SAMPLE_INTERVAL_SECONDS",
    "video_slide_change_threshold": "VIDEO_SLIDE_CHANGE_THRESHOLD",
    "video_slide_min_interval_seconds": "VIDEO_SLIDE_MIN_INTERVAL_SECONDS",
    "video_slide_max_candidates": "VIDEO_SLIDE_MAX_CANDIDATES",
}


def test_every_field_keeps_its_env_alias() -> None:
    actual = {name: field.alias for name, field in Settings.model_fields.items()}
    assert actual == EXPECTED_FIELD_ALIASES


def test_secret_fields_are_exactly_the_two_tokens() -> None:
    assert frozenset({"openai_api_key", "hf_token"}) == SECRET_FIELD_NAMES
    assert set(Settings.model_fields) >= SECRET_FIELD_NAMES


def test_yaml_dict_covers_all_fields_except_secrets() -> None:
    s = Settings(openai_api_key="k", database_url="sqlite:////tmp/t.db")
    assert set(settings_to_yaml_dict(s)) == set(EXPECTED_FIELD_ALIASES) - SECRET_FIELD_NAMES


def test_field_name_construction_still_works() -> None:
    # populate_by_name: tests construct Settings(...) by field name everywhere.
    s = Settings(
        openai_api_key="k",
        database_url="sqlite:////tmp/t.db",
        audio_chunk_seconds=42,
        video_slide_max_candidates=7,
    )
    assert s.audio_chunk_seconds == 42
    assert s.video_slide_max_candidates == 7
