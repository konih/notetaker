"""F9: prerequisite checks for the `doctor` diarization diagnostic.

Each check function is pure and takes its external probe injected, so these tests never
touch the network, the filesystem, or optional heavy imports.
"""

from __future__ import annotations

import pytest
from live_meeting_transcriber.config.settings import Settings
from live_meeting_transcriber.diagnostics import diarization_doctor as doc


def _settings(**overrides: object) -> Settings:
    return Settings(**overrides)  # type: ignore[arg-type]


# --- extras ------------------------------------------------------------------
def test_extras_ok_when_all_import() -> None:
    r = doc.check_extras_installed(import_probe=lambda _m: None)
    assert r.ok
    assert r.remediation is None


def test_extras_fail_lists_missing_and_remediation() -> None:
    def probe(mod: str) -> None:
        if mod.startswith("pyannote"):
            raise ImportError(mod)

    r = doc.check_extras_installed(import_probe=probe)
    assert not r.ok
    assert "pyannote" in r.detail
    assert r.remediation is not None and "uv sync" in r.remediation


# --- ffmpeg ------------------------------------------------------------------
def test_ffmpeg_ok_when_on_path() -> None:
    r = doc.check_ffmpeg(which=lambda c: f"/usr/bin/{c}")
    assert r.ok


def test_ffmpeg_fail_when_missing() -> None:
    r = doc.check_ffmpeg(which=lambda _c: None)
    assert not r.ok
    assert r.remediation is not None


# --- HF token (the two failure modes this session hit) -----------------------
def test_hf_token_missing_is_distinct_from_invalid() -> None:
    def whoami(_t: str) -> dict[str, str]:
        raise AssertionError("whoami must not be called when token is absent")

    r = doc.check_hf_token("", whoami=whoami)
    assert not r.ok
    assert "not set" in r.detail.lower()


def test_hf_token_invalid_reports_rejected() -> None:
    def whoami(_t: str) -> dict[str, str]:
        raise ValueError("Invalid user token")

    r = doc.check_hf_token("hf_bad", whoami=whoami)
    assert not r.ok
    # Must be clearly different wording from the "not set" case.
    assert "not set" not in r.detail.lower()
    assert "invalid" in r.detail.lower() or "rejected" in r.detail.lower()


def test_hf_token_ok_reports_user() -> None:
    r = doc.check_hf_token("hf_good", whoami=lambda _t: {"name": "koniheimel"})
    assert r.ok
    assert "koniheimel" in r.detail


# --- gated model access ------------------------------------------------------
def test_gated_model_ok_when_info_returns() -> None:
    r = doc.check_gated_model_access("hf_good", model_info=lambda _m, _t: object())
    assert r.ok
    # Names the ACTUAL model whisperx pulls, not speaker-diarization-3.1.
    assert "community-1" in r.name


def test_gated_model_fail_links_licence() -> None:
    def model_info(_m: str, _t: str) -> object:
        raise RuntimeError("GatedRepoError 401")

    r = doc.check_gated_model_access("hf_good", model_info=model_info)
    assert not r.ok
    assert r.remediation is not None and "community-1" in r.remediation


def test_gated_model_skipped_without_token() -> None:
    r = doc.check_gated_model_access(None, model_info=lambda _m, _t: object())
    assert not r.ok


# --- device / compute (informational, reflects the B5 resolver) --------------
def test_device_reports_cpu_int8_on_apple_silicon(monkeypatch: pytest.MonkeyPatch) -> None:
    from live_meeting_transcriber.offline import whisperx_pipeline as wp

    monkeypatch.setattr(wp, "_detect_torch_devices", lambda: (False, True))
    r = doc.check_device(_settings())
    assert r.ok
    assert "cpu" in r.detail and "int8" in r.detail


# --- summary helper ----------------------------------------------------------
def test_all_ok_true_only_when_every_result_ok() -> None:
    ok = doc.CheckResult(name="x", ok=True, detail="")
    bad = doc.CheckResult(name="y", ok=False, detail="", remediation="fix it")
    assert doc.all_ok([ok, ok]) is True
    assert doc.all_ok([ok, bad]) is False


def test_device_reports_auto_mps_diarization_on_apple_silicon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # F13: doctor must surface that diarization will auto-run on MPS on Apple Silicon.
    from live_meeting_transcriber.offline import whisperx_pipeline as wp

    monkeypatch.setattr(wp, "_detect_torch_devices", lambda: (False, True))
    monkeypatch.setattr(wp, "_platform_probe", lambda: ("Darwin", "arm64"))
    r = doc.check_device(_settings(whisperx_diarize_device=None))
    assert r.ok
    assert "diarization on 'mps'" in r.detail


def test_device_reports_explicit_diarize_device(monkeypatch: pytest.MonkeyPatch) -> None:
    from live_meeting_transcriber.offline import whisperx_pipeline as wp

    monkeypatch.setattr(wp, "_detect_torch_devices", lambda: (False, False))
    monkeypatch.setattr(wp, "_platform_probe", lambda: ("Linux", "x86_64"))
    r = doc.check_device(_settings(whisperx_diarize_device="cuda:0"))
    assert r.ok
    assert "diarization on 'cuda:0'" in r.detail


# --- offline ASR engine (F12) --------------------------------------------------
def test_offline_engine_auto_mlx_reports_engine() -> None:
    r = doc.check_offline_asr_engine(
        _settings(offline_asr_engine="auto"),
        mlx_importable=lambda: True,
        platform_probe=lambda: ("Darwin", "arm64"),
    )
    assert r.ok
    assert "mlx" in r.detail.lower()


def test_offline_engine_auto_whisperx_reports_engine() -> None:
    r = doc.check_offline_asr_engine(
        _settings(offline_asr_engine="auto"),
        mlx_importable=lambda: False,
        platform_probe=lambda: ("Linux", "x86_64"),
    )
    assert r.ok
    assert "whisperx" in r.detail.lower()


def test_offline_engine_explicit_mlx_unavailable_fails_with_remediation() -> None:
    r = doc.check_offline_asr_engine(
        _settings(offline_asr_engine="mlx"),
        mlx_importable=lambda: False,
        platform_probe=lambda: ("Darwin", "arm64"),
    )
    assert not r.ok
    assert "falling back" in r.detail.lower()
    assert r.remediation is not None and "uv sync --extra mlx" in r.remediation


def test_run_diarization_checks_includes_offline_engine() -> None:
    results = doc.run_diarization_checks(_settings())
    assert any(r.name == "Offline ASR engine" for r in results)
