from __future__ import annotations

from pydantic import BaseModel, Field, ValidationError

from live_meeting_transcriber.domain.models import MeetingMetadataProposal


class StructuredSummaryOutput(BaseModel):
    summary_markdown: str = Field(min_length=1)
    decisions: list[str] = Field(default_factory=list)
    action_items: list[str] = Field(default_factory=list)
    metadata: MeetingMetadataProposal | None = None


def parse_structured_summary_output(data: object) -> StructuredSummaryOutput:
    """Parse LLM JSON payload into a validated structured summary."""
    if not isinstance(data, dict):
        msg = "Summary JSON must be an object"
        raise ValueError(msg)
    try:
        return StructuredSummaryOutput.model_validate(data)
    except ValidationError as e:
        raise ValueError("Invalid structured summary JSON") from e
