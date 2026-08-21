from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


def _bounded_text(value: str, *, name: str, maximum: int, allow_blank: bool = False) -> str:
    if (
        not isinstance(value, str)
        or (not allow_blank and not value.strip())
        or len(value) > maximum
    ):
        raise ValueError(f"{name} is outside its allowed bounds")
    return value


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    message_id: str
    created_at: datetime
    profile_id: str
    speaker: str | None
    source_text: str
    translated_text: str
    source_language: str
    target_language: str = "en"

    def __post_init__(self) -> None:
        _bounded_text(self.message_id, name="message ID", maximum=128)
        _bounded_text(self.profile_id, name="profile ID", maximum=128)
        _bounded_text(self.source_text, name="source text", maximum=8_192)
        _bounded_text(self.translated_text, name="translated text", maximum=8_192)
        _bounded_text(self.source_language, name="source language", maximum=32)
        _bounded_text(self.target_language, name="target language", maximum=32)
        if self.speaker is not None:
            _bounded_text(self.speaker, name="speaker", maximum=200)
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("history timestamp must be timezone-aware")

    @property
    def created_at_utc(self) -> datetime:
        return self.created_at.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class WindowGeometry:
    display_id: str
    x: int
    y: int
    width: int
    height: int
    maximized: bool = False

    def __post_init__(self) -> None:
        _bounded_text(self.display_id, name="display ID", maximum=200)
        if not -100_000 <= self.x <= 100_000 or not -100_000 <= self.y <= 100_000:
            raise ValueError("window position is outside its allowed bounds")
        if not 100 <= self.width <= 50_000 or not 100 <= self.height <= 50_000:
            raise ValueError("window size is outside its allowed bounds")
