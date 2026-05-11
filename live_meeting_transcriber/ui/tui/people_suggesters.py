from __future__ import annotations

from textual.suggester import Suggester

from live_meeting_transcriber.domain.ports import KnownPeopleRepository


class PeoplePrefixSuggester(Suggester):
    """Autocomplete a single name from ``known_people`` (prefix match)."""

    def __init__(self, people: KnownPeopleRepository) -> None:
        super().__init__(use_cache=False, case_sensitive=False)
        self._people = people

    async def get_suggestion(self, value: str) -> str | None:
        part = value.strip()
        if len(part) < 1:
            return None
        candidates = self._people.search_prefix(part, limit=12)
        if not candidates:
            return None
        c0 = candidates[0]
        if len(c0) <= len(part):
            return None
        if not c0.casefold().startswith(part.casefold()):
            return None
        return c0


class CommaSeparatedPeopleSuggester(Suggester):
    """Autocomplete the segment after the last comma (e.g. ``Alice, f`` → ``Alice, Frederik``)."""

    def __init__(self, people: KnownPeopleRepository) -> None:
        super().__init__(use_cache=False, case_sensitive=False)
        self._people = people

    async def get_suggestion(self, value: str) -> str | None:
        if not value.strip():
            return None
        if "," in value:
            head, tail = value.rsplit(",", 1)
            prefix = tail.strip()
            spacer = "" if tail.startswith(" ") else " "
        else:
            head = ""
            prefix = value.strip()
            spacer = ""
        if len(prefix) < 1:
            return None
        candidates = self._people.search_prefix(prefix, limit=12)
        if not candidates:
            return None
        c0 = candidates[0]
        if len(c0) <= len(prefix):
            return None
        if not c0.casefold().startswith(prefix.casefold()):
            return None
        if head:
            return head.rstrip().rstrip(",") + "," + spacer + c0
        return c0
