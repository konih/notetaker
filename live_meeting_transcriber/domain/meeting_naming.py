"""Pure naming rules for meetings (placeholder detection, filename slugs)."""

from __future__ import annotations

import re


def slug_title(title: str, max_len: int = 48) -> str:
    """Lowercase, hyphen-separated, filesystem-safe slug of a session title."""
    s = re.sub(r"[^\w\s-]", "", title, flags=re.UNICODE).strip().lower()
    s = re.sub(r"[-\s]+", "-", s).strip("-")
    return (s[:max_len] if s else "session").rstrip("-")


def is_placeholder_meeting_title(title: str) -> bool:
    """True when the session title looks auto-generated or unset."""
    t = title.strip()
    if not t:
        return True
    if re.match(r"^Meeting \d{4}-\d{2}-\d{2}", t, re.IGNORECASE):
        return True
    if re.match(r"^meeting-\d{4}-\d{2}-\d{2}", t, re.IGNORECASE):
        return True
    return t.lower() in {"meeting", "untitled", "new meeting"}
