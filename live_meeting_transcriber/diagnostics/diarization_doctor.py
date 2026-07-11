"""Prerequisite checks for offline diarization (the `doctor` command).

Each ``check_*`` function is pure: it takes its external probe (imports, ``shutil.which``,
Hugging Face API calls) injected, so it is unit-testable without touching the network,
filesystem, or the optional heavy extras. ``run_diarization_checks`` wires the real probes.

The gated model this checks is the one WhisperX's ``DiarizationPipeline`` actually loads
(``pyannote/speaker-diarization-community-1``) — NOT the ``PYANNOTE_MODEL`` setting
(``speaker-diarization-3.1``), which only feeds the legacy live-diarization provider.
"""

from __future__ import annotations

import importlib
import shutil
from collections.abc import Callable
from dataclasses import dataclass

from live_meeting_transcriber.config.settings import Settings

# What whisperx.diarize.DiarizationPipeline pulls by default (verified empirically 2026-07-10).
DIARIZATION_MODEL_ID = "pyannote/speaker-diarization-community-1"
_TOKENS_URL = "https://huggingface.co/settings/tokens"


@dataclass(frozen=True)
class CheckResult:
    """One prerequisite check outcome. ``remediation`` is a copy-pasteable next step."""

    name: str
    ok: bool
    detail: str
    remediation: str | None = None


def all_ok(results: list[CheckResult]) -> bool:
    return all(r.ok for r in results)


# --- individual checks -------------------------------------------------------
def check_extras_installed(
    *, import_probe: Callable[[str], object] = importlib.import_module
) -> CheckResult:
    """WhisperX + pyannote.audio must import (the offline finalize extras)."""
    name = "WhisperX + pyannote extras"
    missing: list[str] = []
    for mod in ("whisperx", "pyannote.audio"):
        try:
            import_probe(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        return CheckResult(
            name,
            False,
            f"not importable: {', '.join(missing)}",
            "uv sync --extra whisperx --extra diarization (needs Python <= 3.13 for torch)",
        )
    return CheckResult(name, True, "importable")


def check_ffmpeg(*, which: Callable[[str], str | None] = shutil.which) -> CheckResult:
    """ffmpeg + ffprobe decode the session WAV and probe media."""
    name = "ffmpeg / ffprobe"
    missing = [cmd for cmd in ("ffmpeg", "ffprobe") if which(cmd) is None]
    if missing:
        return CheckResult(
            name,
            False,
            f"not on PATH: {', '.join(missing)}",
            "macOS: brew install ffmpeg  ·  Linux: sudo apt install ffmpeg",
        )
    return CheckResult(name, True, "found on PATH")


def check_hf_token(token: str | None, *, whoami: Callable[[str], object]) -> CheckResult:
    """Distinguish a *missing* token from an *invalid* one — the two failure modes seen."""
    name = "Hugging Face token"
    if not token or not token.strip():
        return CheckResult(
            name,
            False,
            "HF_TOKEN is not set",
            f"Create a read token at {_TOKENS_URL} and set HF_TOKEN in .env (or your shell env)",
        )
    try:
        info = whoami(token.strip())
    except Exception as e:
        return CheckResult(
            name,
            False,
            f"HF_TOKEN is set but invalid/rejected ({type(e).__name__})",
            f"Regenerate the token at {_TOKENS_URL} and update HF_TOKEN",
        )
    user = info.get("name") if isinstance(info, dict) else None
    return CheckResult(name, True, f"authenticated as {user}" if user else "authenticated")


def check_gated_model_access(
    token: str | None,
    *,
    model_id: str = DIARIZATION_MODEL_ID,
    model_info: Callable[[str, str], object],
) -> CheckResult:
    """The gated pyannote model must be accessible (licence accepted for the token's account)."""
    name = f"Gated model access ({model_id.split('/')[-1]})"
    licence_url = f"https://hf.co/{model_id}"
    if not token or not token.strip():
        return CheckResult(
            name,
            False,
            "no valid HF_TOKEN to check with",
            f"set HF_TOKEN, then accept {licence_url}",
        )
    try:
        model_info(model_id, token.strip())
    except Exception as e:
        return CheckResult(
            name,
            False,
            f"cannot access {model_id} ({type(e).__name__})",
            f"Accept the licence at {licence_url} while logged in as the token's account",
        )
    return CheckResult(name, True, f"{model_id} accessible")


def check_device(settings: Settings) -> CheckResult:
    """Informational: report the ASR + diarization devices the finalize pass will use."""
    from live_meeting_transcriber.offline import whisperx_pipeline as wp

    has_cuda, has_mps = wp._detect_torch_devices()
    device = wp._resolve_asr_device(settings)
    compute = wp._resolve_compute_type(settings, device)
    align_device = wp._resolve_torch_device(settings, device)
    diarize_device = wp._resolve_diarize_device(settings, align_device)
    detail = (
        f"ASR will run on device={device!r}, compute={compute!r}; diarization on {diarize_device!r}"
    )
    if has_mps and not has_cuda:
        detail += " — Apple Silicon: CTranslate2 has no MPS backend, so the ASR stays on CPU"
    return CheckResult("Device / compute", True, detail)


# --- orchestration -----------------------------------------------------------
def _hf_probes() -> tuple[Callable[[str], object], Callable[[str, str], object]] | None:
    """Return (whoami, model_info) backed by huggingface_hub, or None if it is absent."""
    try:
        from huggingface_hub import HfApi
    except ImportError:
        return None
    api = HfApi()
    return (lambda t: api.whoami(token=t), lambda m, t: api.model_info(m, token=t))


def run_diarization_checks(settings: Settings) -> list[CheckResult]:
    """Run every prerequisite check in a sensible order and return their results."""
    results: list[CheckResult] = []
    extras = check_extras_installed()
    results.append(extras)
    results.append(check_ffmpeg())

    token = settings.hf_token
    probes = _hf_probes()
    if probes is None:
        results.append(
            CheckResult(
                "Hugging Face token",
                False,
                "huggingface_hub not installed",
                "uv sync --extra whisperx",
            )
        )
    else:
        whoami, model_info = probes
        token_result = check_hf_token(token, whoami=whoami)
        results.append(token_result)
        if token_result.ok:
            results.append(check_gated_model_access(token, model_info=model_info))

    if extras.ok:
        results.append(check_device(settings))
    return results
