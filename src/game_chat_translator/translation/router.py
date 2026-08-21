from __future__ import annotations

import hashlib
from collections import OrderedDict
from contextlib import suppress

from game_chat_translator.models import TranslationResult
from game_chat_translator.translation.base import (
    CancellationToken,
    TranslationCancelled,
    TranslationOutcome,
    TranslationProvider,
    TranslationProviderError,
    TranslationRequest,
    TranslationTimedOut,
)


class TranslationRouter:
    def __init__(
        self,
        contextual: TranslationProvider | None,
        lightweight: TranslationProvider | None,
        *,
        timeout_seconds: float = 5.0,
        maximum_attempts: int = 2,
        cache_size: int = 256,
        additional_fallbacks: tuple[TranslationProvider, ...] = (),
    ) -> None:
        if timeout_seconds <= 0 or maximum_attempts not in (1, 2) or cache_size <= 0:
            raise ValueError("invalid translation router limits")
        self._contextual = contextual
        self._lightweight = lightweight
        self._fallbacks = tuple(
            provider
            for provider in ((lightweight,) if lightweight is not None else ())
            + additional_fallbacks
        )
        self._timeout = timeout_seconds
        self._maximum_attempts = maximum_attempts
        self._cache_size = cache_size
        self._cache: OrderedDict[str, TranslationOutcome] = OrderedDict()
        self._closed = False

    def translate(
        self, request: TranslationRequest, cancellation: CancellationToken | None = None
    ) -> TranslationOutcome:
        if cancellation is not None and cancellation.cancelled:
            raise TranslationCancelled("translation was cancelled")
        key = _cache_key(request)
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached

        failures: list[str] = []
        total_attempts = 0
        providers = (((self._contextual, False),) if self._contextual is not None else ()) + tuple(
            (provider, True) for provider in self._fallbacks
        )
        for provider, fallback in providers:
            if provider is None or not _healthy(provider):
                failures.append("TRANSLATION_PROVIDER_UNAVAILABLE")
                continue
            for attempt in range(1, self._maximum_attempts + 1):
                total_attempts += 1
                if cancellation is not None and cancellation.cancelled:
                    raise TranslationCancelled("translation was cancelled")
                try:
                    natural = provider.translate(
                        request, timeout_seconds=self._timeout, cancellation=cancellation
                    ).strip()
                    if not natural:
                        raise TranslationProviderError("provider returned empty output")
                    _verify_protected_terms(natural, request.protected_terms)
                except TranslationCancelled:
                    raise
                except TranslationTimedOut:
                    failures.append("TRANSLATION_TIMEOUT")
                    break
                except TranslationProviderError as exc:
                    failures.append("TRANSLATION_PROVIDER_FAILED")
                    if not exc.retryable or attempt == self._maximum_attempts:
                        break
                    continue
                result = TranslationResult(
                    source=request.source_text,
                    target_language=request.target_language,
                    natural_text=natural,
                    provider=provider.provider_id,
                    model_id=provider.model_id,
                    confidence=0.7 if fallback else 0.9,
                    warnings=("lightweight offline fallback",) if fallback else (),
                )
                outcome = TranslationOutcome(
                    result,
                    "TRANSLATION_LIGHTWEIGHT_FALLBACK" if fallback else None,
                    fallback,
                    total_attempts,
                )
                self._remember(key, outcome)
                return outcome
        code = failures[-1] if failures else "TRANSLATION_UNAVAILABLE"
        return self._original(request, code, max(1, total_attempts))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        seen: set[int] = set()
        for provider in (self._contextual, *self._fallbacks):
            if provider is not None and id(provider) not in seen:
                seen.add(id(provider))
                with suppress(Exception):
                    provider.close()
        self._cache.clear()

    def _original(
        self, request: TranslationRequest, error_code: str, attempts: int = 1
    ) -> TranslationOutcome:
        result = TranslationResult(
            source=request.source_text,
            target_language=request.target_language,
            natural_text=request.source_text,
            provider="untranslated",
            confidence=0.0,
            warnings=("translation unavailable; showing original text",),
        )
        return TranslationOutcome(result, error_code, True, attempts)

    def _remember(self, key: str, outcome: TranslationOutcome) -> None:
        self._cache[key] = outcome
        self._cache.move_to_end(key)
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)


def _cache_key(request: TranslationRequest) -> str:
    digest = hashlib.sha256()
    for value in (
        request.source_text,
        request.source_language,
        request.target_language,
        "\x1f".join(request.protected_terms),
        "\x1f".join(request.context),
        str(request.context_generation),
        str(request.glossary_generation),
        str(request.model_generation),
    ):
        digest.update(value.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _healthy(provider: TranslationProvider) -> bool:
    try:
        return provider.health_check()
    except Exception:
        return False


def _verify_protected_terms(output: str, terms: tuple[str, ...]) -> None:
    if any(term not in output for term in terms):
        raise TranslationProviderError("provider changed a protected term")
