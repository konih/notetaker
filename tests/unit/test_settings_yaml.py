"""U21 — YAML config store as source of truth + atomic write-back.

Precedence: explicit env var > config.yaml > .env (back-compat) > field default.
Secrets (API keys / tokens) are never written to the plaintext YAML file.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from live_meeting_transcriber.config.settings import (
    Settings,
    default_config_yaml_path,
    load_settings,
    save_settings,
)


@pytest.fixture
def xdg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point XDG_CONFIG_HOME at a temp dir and return the app config dir."""
    root = tmp_path / "xdg"
    config_dir = root / "live-meeting-transcriber"
    config_dir.mkdir(parents=True)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(root))
    monkeypatch.chdir(tmp_path)  # avoid picking up a repo .env
    return config_dir


def _clear_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "TRANSCRIPTION_MODEL",
        "SUMMARY_MODEL",
        "AUDIO_CHUNK_SECONDS",
        "OPENAI_API_KEY",
        "HF_TOKEN",
        "LOG_FILE",
        "OBSIDIAN_PEOPLE_DIR",
    ):
        monkeypatch.delenv(var, raising=False)


def test_default_config_yaml_path_under_xdg(xdg: Path) -> None:
    assert default_config_yaml_path() == xdg / "config.yaml"


def test_yaml_is_source_of_truth(xdg: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_settings_env(monkeypatch)
    (xdg / "config.yaml").write_text(
        "transcription_model: from-yaml\naudio_chunk_seconds: 22\n", encoding="utf-8"
    )
    s = load_settings()
    assert s.transcription_model == "from-yaml"
    assert s.audio_chunk_seconds == 22


def test_env_overrides_yaml(xdg: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_settings_env(monkeypatch)
    (xdg / "config.yaml").write_text("transcription_model: from-yaml\n", encoding="utf-8")
    monkeypatch.setenv("TRANSCRIPTION_MODEL", "from-env")
    assert load_settings().transcription_model == "from-env"


def test_yaml_overrides_dotenv(xdg: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_settings_env(monkeypatch)
    (xdg / ".env").write_text("TRANSCRIPTION_MODEL=from-dotenv\n", encoding="utf-8")
    (xdg / "config.yaml").write_text("transcription_model: from-yaml\n", encoding="utf-8")
    assert load_settings().transcription_model == "from-yaml"


def test_dotenv_used_when_no_yaml(xdg: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_settings_env(monkeypatch)
    (xdg / ".env").write_text("TRANSCRIPTION_MODEL=from-dotenv\n", encoding="utf-8")
    assert load_settings().transcription_model == "from-dotenv"


def test_save_settings_round_trip_no_field_loss(
    xdg: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear_settings_env(monkeypatch)
    people = tmp_path / "vault" / "People"
    people.mkdir(parents=True)
    log_file = tmp_path / "logs" / "app.log"
    log_file.parent.mkdir(parents=True)

    base = load_settings()
    edited = base.model_copy(
        update={
            "transcription_model": "edited-model",
            "audio_stereo_mode": "dual_path",  # Literal
            "audio_chunk_seconds": 30,
            "diarization_num_speakers": 4,  # int | None
            "obsidian_people_dir": people.resolve(),  # Path | None
            "log_file": log_file.resolve(),  # Path | None
            "faster_whisper_language": None,  # str | None stays None
        }
    )
    path = save_settings(edited)
    assert path == default_config_yaml_path()
    assert path.is_file()

    reloaded = load_settings()
    assert reloaded.transcription_model == "edited-model"
    assert reloaded.audio_stereo_mode == "dual_path"
    assert reloaded.audio_chunk_seconds == 30
    assert reloaded.diarization_num_speakers == 4
    assert reloaded.obsidian_people_dir == people.resolve()
    assert reloaded.log_file == log_file.resolve()
    assert reloaded.faster_whisper_language is None


def test_save_settings_serialises_paths_as_strings(
    xdg: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear_settings_env(monkeypatch)
    d = tmp_path / "vault"
    d.mkdir()
    edited = load_settings().model_copy(update={"obsidian_people_dir": d.resolve()})
    save_settings(edited)
    raw = yaml.safe_load((xdg / "config.yaml").read_text(encoding="utf-8"))
    assert raw["obsidian_people_dir"] == str(d.resolve())
    assert isinstance(raw["obsidian_people_dir"], str)


def test_save_settings_excludes_secrets(
    xdg: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_settings_env(monkeypatch)
    edited = load_settings().model_copy(
        update={"openai_api_key": "sk-secret", "hf_token": "hf-secret"}
    )
    save_settings(edited)
    text = (xdg / "config.yaml").read_text(encoding="utf-8")
    raw = yaml.safe_load(text)
    assert "openai_api_key" not in raw
    assert "hf_token" not in raw
    assert "sk-secret" not in text
    assert "hf-secret" not in text


def test_save_settings_is_atomic_overwrite(
    xdg: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_settings_env(monkeypatch)
    (xdg / "config.yaml").write_text("transcription_model: old\n", encoding="utf-8")
    save_settings(load_settings().model_copy(update={"transcription_model": "new"}))
    raw = yaml.safe_load((xdg / "config.yaml").read_text(encoding="utf-8"))
    assert raw["transcription_model"] == "new"
    # no stray temp files left behind
    assert list(xdg.glob("*.tmp*")) == []


def test_seed_from_current_imports_dotenv(
    xdg: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """First save with no config.yaml seeds it from resolved settings (incl .env)."""
    _clear_settings_env(monkeypatch)
    (xdg / ".env").write_text("TRANSCRIPTION_MODEL=from-dotenv\n", encoding="utf-8")
    assert not default_config_yaml_path().exists()
    save_settings(load_settings())
    raw = yaml.safe_load((xdg / "config.yaml").read_text(encoding="utf-8"))
    assert raw["transcription_model"] == "from-dotenv"


def test_settings_type_class_smoke() -> None:
    # Guard: Settings still constructs on bare defaults.
    assert isinstance(Settings.model_construct(), Settings)
