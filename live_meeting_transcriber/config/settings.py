"""Application settings: one flat model composed from per-area sections (A8).

``Settings`` multiple-inherits the section models in ``config/sections/``;
pydantic collects every section's fields onto this single flat model, so each
field keeps its exact flat env-var alias (``AUDIO_CHUNK_SECONDS``-style) and the
U21 resolution order — env var > ``config.yaml`` > ``.env`` > default — is
unchanged by the split. Path/XDG helpers live in ``config/paths.py`` and are
re-exported here for backwards-compatible imports.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path

import yaml
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

from live_meeting_transcriber.config.paths import (
    APP_CONFIG_DIR_NAME,
    APP_CONFIG_YAML_NAME,
    APP_DATA_DIR_NAME,
    app_config_dir,
    default_config_yaml_path,
    default_data_dir,
    default_database_url,
    discover_env_file_paths,
    xdg_config_home,
)
from live_meeting_transcriber.config.sections import (
    AudioSettings,
    DiarizationSettings,
    LoggingSettings,
    ObsidianSettings,
    ProviderSettings,
    ScreenshotSettings,
    StorageSettings,
    VideoSettings,
    WhisperXSettings,
)

__all__ = [
    "APP_CONFIG_DIR_NAME",
    "APP_CONFIG_YAML_NAME",
    "APP_DATA_DIR_NAME",
    "SECRET_FIELD_NAMES",
    "Settings",
    "app_config_dir",
    "default_config_yaml_path",
    "default_data_dir",
    "default_database_url",
    "discover_env_file_paths",
    "load_settings",
    "save_settings",
    "settings_to_yaml_dict",
    "xdg_config_home",
]

# Secrets are never written to the plaintext YAML config (U21, OQ-U21-2). Set them via an
# environment variable or ``.env``; they still load normally, they are just excluded from
# write-back so an API key/token never lands on disk in cleartext.
SECRET_FIELD_NAMES = frozenset({"openai_api_key", "hf_token"})

_CONFIG_YAML_HEADER = (
    "# live-meeting-transcriber configuration (U21).\n"
    "# Source of truth for settings, regenerated on every in-app save — user comments\n"
    "# are NOT preserved. Precedence: environment variable > this file > .env > default.\n"
    "# Secrets (API keys / tokens) are intentionally not stored here; set them via env or .env.\n"
    "\n"
)


class Settings(
    ProviderSettings,
    StorageSettings,
    AudioSettings,
    LoggingSettings,
    WhisperXSettings,
    DiarizationSettings,
    ObsidianSettings,
    ScreenshotSettings,
    VideoSettings,
):
    """All configuration areas merged into the one model the app constructs."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Insert the YAML store between env and .env (U21).

        Precedence (highest first): constructor kwargs > environment variable >
        ``config.yaml`` > ``.env`` (back-compat) > field default. The YAML path is
        resolved at construction time so tests can redirect ``XDG_CONFIG_HOME``.
        """
        yaml_source = YamlConfigSettingsSource(settings_cls, yaml_file=default_config_yaml_path())
        return (init_settings, env_settings, yaml_source, dotenv_settings, file_secret_settings)


def load_settings() -> Settings:
    env_files = discover_env_file_paths()
    if env_files:
        return Settings(_env_file=tuple(str(p) for p in env_files))
    return Settings()


def settings_to_yaml_dict(settings: Settings) -> dict[str, object]:
    """Serialise settings for the YAML store: JSON-safe values, secrets stripped.

    ``mode="json"`` renders ``Path`` fields as strings and ``None`` as null so the dump
    round-trips through :class:`YamlConfigSettingsSource` without Python-object tags.
    """
    data: dict[str, object] = settings.model_dump(mode="json", by_alias=False)
    for secret in SECRET_FIELD_NAMES:
        data.pop(secret, None)
    return data


def save_settings(settings: Settings, path: Path | None = None) -> Path:
    """Atomically write the full settings set to the YAML store and return its path.

    The file is regenerated from scratch (comments are not preserved) and written via a
    temp file + ``os.replace`` so a crashed write never truncates the existing config. On
    first save with no ``config.yaml`` this seeds the file from the currently resolved
    settings, importing any ``.env``/env values into the store.
    """
    target = path or default_config_yaml_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump(
        settings_to_yaml_dict(settings),
        sort_keys=True,
        default_flow_style=False,
        allow_unicode=True,
    )
    fd, tmp_name = tempfile.mkstemp(dir=str(target.parent), prefix="config-", suffix=".yaml.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(_CONFIG_YAML_HEADER)
            handle.write(body)
        os.replace(tmp_name, target)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_name)
        raise
    return target
