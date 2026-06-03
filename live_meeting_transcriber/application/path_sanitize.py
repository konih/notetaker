"""Normalize user-supplied import paths (shell quotes, whitespace)."""

from __future__ import annotations


def normalize_import_path(raw: str) -> str:
    """Strip surrounding whitespace and optional matching quote characters."""
    s = raw.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "'\"":
        s = s[1:-1].strip()
    return s
