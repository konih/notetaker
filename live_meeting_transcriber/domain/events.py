from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class SessionStarted:
    session_id: UUID
    at: datetime


@dataclass(frozen=True)
class SessionEnded:
    session_id: UUID
    at: datetime
