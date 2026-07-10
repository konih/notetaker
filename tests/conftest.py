from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_xdg_config_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Isolate settings from the host's real ``~/.config`` for every test.

    Since U21 wired the YAML store into ``Settings`` via ``settings_customise_sources``,
    *any* ``Settings()`` construction now reads ``$XDG_CONFIG_HOME/live-meeting-transcriber/
    config.yaml``. Without this, a developer who has used the app locally would have their
    real ``config.yaml`` bleed into the suite. Tests may still override ``XDG_CONFIG_HOME``.
    """
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path_factory.mktemp("xdg-config")))
