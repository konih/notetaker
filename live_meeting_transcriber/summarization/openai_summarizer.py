from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from openai import AsyncOpenAI

from live_meeting_transcriber.domain.models import (
    ActionItem,
    Decision,
    MeetingSession,
    ProviderMetadata,
    Summary,
    TranscriptSegment,
)
from live_meeting_transcriber.obsidian.vault_patterns import load_vault_naming_hints
from live_meeting_transcriber.summarization.service import build_summary_prompt
from live_meeting_transcriber.summarization.structured_output import parse_structured_summary_output


class OpenAISummarizationError(RuntimeError):
    pass


class OpenAISummarizationProvider:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        vault_meetings_dir: Path | None = None,
    ) -> None:
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model
        self._vault_meetings_dir = vault_meetings_dir

    async def summarize(
        self,
        *,
        session: MeetingSession,
        segments: Iterable[TranscriptSegment],
        speaker_display: dict[str, str] | None = None,
        user_context: str | None = None,
    ) -> Summary:
        vault_hints = load_vault_naming_hints(self._vault_meetings_dir)
        prompt = build_summary_prompt(
            session=session,
            segments=segments,
            speaker_display=speaker_display,
            user_context=user_context,
            vault_hints=vault_hints,
        )
        try:
            resp = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": "Return only valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
            )
        except Exception as e:
            raise OpenAISummarizationError(str(e)) from e

        content = resp.choices[0].message.content if resp.choices else None
        if not content:
            raise OpenAISummarizationError("OpenAI summarization returned empty content")

        try:
            data = json.loads(content)
            parsed = parse_structured_summary_output(data)
        except (json.JSONDecodeError, ValueError) as e:
            raise OpenAISummarizationError("Failed to parse JSON summary output") from e

        return Summary(
            session_id=session.id,
            summary_markdown=parsed.summary_markdown,
            decisions=[Decision(session_id=session.id, text=t) for t in parsed.decisions],
            action_items=[ActionItem(session_id=session.id, text=t) for t in parsed.action_items],
            meeting_metadata=parsed.metadata,
            metadata=ProviderMetadata(provider="openai", model=self._model, extra={}),
        )
