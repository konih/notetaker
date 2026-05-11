from __future__ import annotations

import json
from collections.abc import Iterable

from openai import AsyncOpenAI
from pydantic import BaseModel, Field, ValidationError

from live_meeting_transcriber.domain.models import (
    ActionItem,
    Decision,
    MeetingSession,
    ProviderMetadata,
    Summary,
    TranscriptSegment,
)
from live_meeting_transcriber.summarization.service import build_summary_prompt


class OpenAISummarizationError(RuntimeError):
    pass


class _SummaryOutput(BaseModel):
    summary_markdown: str = Field(min_length=1)
    decisions: list[str] = Field(default_factory=list)
    action_items: list[str] = Field(default_factory=list)


class OpenAISummarizationProvider:
    def __init__(self, *, api_key: str, model: str) -> None:
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    async def summarize(self, *, session: MeetingSession, segments: Iterable[TranscriptSegment]) -> Summary:
        prompt = build_summary_prompt(session=session, segments=segments)
        try:
            resp = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": "Return only valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
            )
        except Exception as e:  # noqa: BLE001
            raise OpenAISummarizationError(str(e)) from e

        content = resp.choices[0].message.content if resp.choices else None
        if not content:
            raise OpenAISummarizationError("OpenAI summarization returned empty content")

        try:
            data = json.loads(content)
            parsed = _SummaryOutput.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as e:
            raise OpenAISummarizationError("Failed to parse JSON summary output") from e

        return Summary(
            session_id=session.id,
            summary_markdown=parsed.summary_markdown,
            decisions=[Decision(session_id=session.id, text=t) for t in parsed.decisions],
            action_items=[ActionItem(session_id=session.id, text=t) for t in parsed.action_items],
            metadata=ProviderMetadata(provider="openai", model=self._model, extra={}),
        )

