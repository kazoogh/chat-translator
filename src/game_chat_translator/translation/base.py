from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from game_chat_translator.models import TranslationResult


class CancellationToken(Protocol):
    @property
    def cancelled(self) -> bool: ...


class TranslationProviderError(RuntimeError):
    """Safe provider-boundary failure without source chat content."""

    retryable: bool = False

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class TranslationTimedOut(TranslationProviderError):
    pass


class TranslationCancelled(TranslationProviderError):
    pass


@dataclass(frozen=True, slots=True)
class TranslationRequest:
    source_text: str
    source_language: str
    target_language: str
    protected_terms: tuple[str, ...]
    context: tuple[str, ...]
    prompt: str
    context_generation: int
    glossary_generation: int
    model_generation: int


@dataclass(frozen=True, slots=True)
class TranslationOutcome:
    result: TranslationResult
    error_code: str | None = None
    degraded: bool = False
    attempts: int = 1


class TranslationProvider(Protocol):
    @property
    def provider_id(self) -> str: ...

    @property
    def model_id(self) -> str | None: ...

    def health_check(self) -> bool: ...

    def translate(
        self,
        request: TranslationRequest,
        *,
        timeout_seconds: float,
        cancellation: CancellationToken | None = None,
    ) -> str: ...

    def close(self) -> None: ...
