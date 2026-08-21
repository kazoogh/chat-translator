from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from game_chat_translator.models import OcrFragment


class ProviderHealth(StrEnum):
    UNINITIALIZED = "uninitialized"
    LOADING = "loading"
    READY = "ready"
    DEGRADED = "degraded"
    FAILED = "failed"
    STOPPED = "stopped"


class OcrProviderError(RuntimeError):
    pass


class OcrCancelled(OcrProviderError):
    pass


class CancellationToken(Protocol):
    @property
    def cancelled(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class OcrInput:
    pixels: bytes
    width: int
    height: int
    channels: int
    generation: int

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("OCR input dimensions must be positive")
        if self.width > 8_192 or self.height > 8_192:
            raise ValueError("OCR input dimensions exceed the safe limit")
        if self.channels not in (1, 3, 4):
            raise ValueError("OCR input channels must be 1, 3, or 4")
        if self.generation < 0:
            raise ValueError("OCR generation cannot be negative")
        if len(self.pixels) != self.width * self.height * self.channels:
            raise ValueError("OCR input buffer length does not match dimensions")


@dataclass(frozen=True, slots=True)
class OcrOutcome:
    fragments: tuple[OcrFragment, ...]
    health: ProviderHealth
    generation: int
    error_code: str | None = None


class OcrProvider(Protocol):
    @property
    def health(self) -> ProviderHealth: ...

    def health_check(self) -> bool: ...

    def recognize(
        self, request: OcrInput, cancellation: CancellationToken | None = None
    ) -> tuple[OcrFragment, ...]: ...

    def close(self) -> None: ...
