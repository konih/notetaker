"""Drift guard: every configurable env var must be documented (D3, DOC-02).

The audit repeatedly found ``docs/configuration.md`` lagging the ``Settings`` model —
new env vars ship undocumented. Rather than re-audit by hand, this test introspects the
model's aliases and asserts each one appears (as a whole token) in the configuration doc.
A hardcoded list would rot the same way the docs do, so we derive the list from the model.
"""

from __future__ import annotations

import re
from pathlib import Path

from live_meeting_transcriber.config.settings import Settings

_DOC = Path(__file__).resolve().parents[2] / "docs" / "configuration.md"

# Aliases intentionally left out of the user-facing configuration reference, each with a
# one-line justification. Keep this empty unless there is a real reason — the whole point of
# the guard is that undocumented knobs are visible here, not silently dropped from the docs.
_UNDOCUMENTED_ALIASES: dict[str, str] = {}


def _settings_aliases() -> list[str]:
    """Every env-var alias declared on the ``Settings`` model."""
    aliases: list[str] = []
    for field in Settings.model_fields.values():
        alias = field.alias
        if alias and alias.isupper():
            aliases.append(alias)
    return aliases


def _token_in_doc(token: str, doc: str) -> bool:
    """True when ``token`` appears in ``doc`` as a whole word.

    Underscore is a word char, so a naive substring check would let ``LOG_FILE`` match
    inside ``LOG_FILE_MAX_MB``. Guard both sides against the identifier character class so
    only a standalone mention counts.
    """
    return re.search(rf"(?<![A-Z0-9_]){re.escape(token)}(?![A-Z0-9_])", doc) is not None


def test_every_settings_alias_is_documented() -> None:
    doc = _DOC.read_text(encoding="utf-8")
    aliases = _settings_aliases()

    missing = [
        alias
        for alias in aliases
        if alias not in _UNDOCUMENTED_ALIASES and not _token_in_doc(alias, doc)
    ]

    assert not missing, (
        "docs/configuration.md is missing these env vars declared on Settings:\n"
        + "\n".join(f"  - {a}" for a in sorted(missing))
        + "\nDocument them, or add to _UNDOCUMENTED_ALIASES with a justification."
    )


def test_exclusion_allowlist_has_no_stale_entries() -> None:
    """Every excluded alias must still exist on the model (no stale exclusions)."""
    aliases = set(_settings_aliases())
    stale = [a for a in _UNDOCUMENTED_ALIASES if a not in aliases]
    assert not stale, f"_UNDOCUMENTED_ALIASES references aliases no longer on Settings: {stale}"
