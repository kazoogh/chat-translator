from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from game_chat_translator.models import MessageClass
from game_chat_translator.translation.prompting import ContextMessage


@dataclass(frozen=True, slots=True)
class ContextEntry:
    speaker: str | None
    channel: str | None
    created_at: datetime
    monotonic_seconds: float
    language: str
    direction: MessageClass
    source_text: str
    translated_text: str | None = None

    def __post_init__(self) -> None:
        if self.created_at.tzinfo is None:
            raise ValueError("context timestamp must be timezone-aware")
        if self.monotonic_seconds < 0:
            raise ValueError("context monotonic time cannot be negative")


class ContextManager:
    """Short-lived in-memory context; it never persists conversation content."""

    def __init__(
        self,
        *,
        maximum_messages: int = 10,
        maximum_age_seconds: float = 300.0,
        monotonic: Callable[[], float],
    ) -> None:
        if not 3 <= maximum_messages <= 10 or maximum_age_seconds <= 0:
            raise ValueError("invalid context bounds")
        self._maximum = maximum_messages
        self._maximum_age = maximum_age_seconds
        self._monotonic = monotonic
        self._entries: deque[ContextEntry] = deque(maxlen=maximum_messages)
        self._generation = 0

    @property
    def generation(self) -> int:
        return self._generation

    def add(self, entry: ContextEntry) -> None:
        self._expire()
        self._entries.append(entry)
        self._generation += 1

    def snapshot(self) -> tuple[ContextMessage, ...]:
        self._expire()
        return tuple(
            ContextMessage(item.speaker, item.source_text, item.translated_text)
            for item in self._entries
        )

    def clear(self) -> None:
        self._entries.clear()
        self._generation += 1

    def _expire(self) -> None:
        cutoff = self._monotonic() - self._maximum_age
        removed = False
        while self._entries and self._entries[0].monotonic_seconds < cutoff:
            self._entries.popleft()
            removed = True
        if removed:
            self._generation += 1
