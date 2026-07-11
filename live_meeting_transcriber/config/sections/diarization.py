"""Diarization settings: pyannote model, HF token, and speaker-count hints."""

from __future__ import annotations

from typing import Self, cast

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings


class DiarizationSettings(BaseSettings):
    """Speaker attribution (legacy chunk diarization removed; kept for HF token reuse / docs)."""

    diarization_enabled: bool = Field(default=False, alias="DIARIZATION_ENABLED")
    diarization_provider: str = Field(default="noop", alias="DIARIZATION_PROVIDER")
    hf_token: str | None = Field(default=None, alias="HF_TOKEN")
    pyannote_model: str = Field(
        default="pyannote/speaker-diarization-3.1",
        alias="PYANNOTE_MODEL",
    )
    # Hints for pyannote Pipeline(audio, **kwargs). When you know the meeting size, setting
    # DIARIZATION_NUM_SPEAKERS (or min/max) often fixes "everything is speaker_1" on mixed mono.
    diarization_num_speakers: int | None = Field(
        default=None, alias="DIARIZATION_NUM_SPEAKERS", ge=1, le=32
    )
    diarization_min_speakers: int | None = Field(
        default=None, alias="DIARIZATION_MIN_SPEAKERS", ge=1, le=32
    )
    diarization_max_speakers: int | None = Field(
        default=None, alias="DIARIZATION_MAX_SPEAKERS", ge=1, le=32
    )

    @field_validator(
        "diarization_num_speakers",
        "diarization_min_speakers",
        "diarization_max_speakers",
        mode="before",
    )
    @classmethod
    def _optional_diarization_int(cls, v: object) -> int | None:
        if v is None or v == "":
            return None
        return int(cast("str | int | float", v))

    @model_validator(mode="after")
    def _diarization_speaker_bounds(self) -> Self:
        mn, mx = self.diarization_min_speakers, self.diarization_max_speakers
        if mn is not None and mx is not None and mn > mx:
            msg = "DIARIZATION_MIN_SPEAKERS must be <= DIARIZATION_MAX_SPEAKERS"
            raise ValueError(msg)
        return self

    def pyannote_diarization_pipeline_kwargs(self) -> dict[str, int]:
        """Keyword arguments for pyannote ``Pipeline.__call__(audio, **kwargs)``."""
        if self.diarization_num_speakers is not None:
            return {"num_speakers": int(self.diarization_num_speakers)}
        out: dict[str, int] = {}
        if self.diarization_min_speakers is not None:
            out["min_speakers"] = int(self.diarization_min_speakers)
        if self.diarization_max_speakers is not None:
            out["max_speakers"] = int(self.diarization_max_speakers)
        return out
