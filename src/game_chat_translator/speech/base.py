from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class SpeechSettings:
    rate: int = 0
    volume: int = 100
    voice_id: str | None = None

    def __post_init__(self) -> None:
        if not -10 <= self.rate <= 10:
            raise ValueError("speech rate must be between -10 and 10")
        if not 0 <= self.volume <= 100:
            raise ValueError("speech volume must be between 0 and 100")


@dataclass(frozen=True, slots=True)
class SpeechJob:
    message_id: UUID
    text: str
    priority: int = 0
    expires_monotonic: float | None = None
    diagnostic: bool = False

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("speech text cannot be blank")
        if self.expires_monotonic is not None and self.expires_monotonic < 0:
            raise ValueError("speech expiry cannot be negative")


class SpeechCancellation(Protocol):
    @property
    def cancelled(self) -> bool: ...


class SpeechProvider(Protocol):
    def voices(self) -> tuple[tuple[str, str], ...]: ...

    def speak(
        self,
        text: str,
        settings: SpeechSettings,
        *,
        cancellation: SpeechCancellation,
    ) -> None: ...

    def cancel(self) -> None: ...

    def close(self) -> None: ...


class SpeechProviderError(RuntimeError):
    """Safe speech-provider failure that contains no chat text."""
