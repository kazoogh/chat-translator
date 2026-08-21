from __future__ import annotations

from dataclasses import dataclass

import pytest

from game_chat_translator.translation.base import (
    TranslationCancelled,
    TranslationProviderError,
    TranslationTimedOut,
)
from game_chat_translator.translation.prompting import TranslationRequestBuilder
from game_chat_translator.translation.router import TranslationRouter


@dataclass
class FakeProvider:
    provider_id: str
    outputs: list[str | Exception]
    model_id: str | None = "fake-model"
    healthy: bool = True
    calls: int = 0
    closes: int = 0

    def health_check(self) -> bool:
        return self.healthy

    def translate(
        self, request: object, *, timeout_seconds: float, cancellation: object = None
    ) -> str:
        del request, cancellation
        assert timeout_seconds == 0.25
        value = self.outputs[min(self.calls, len(self.outputs) - 1)]
        self.calls += 1
        if isinstance(value, Exception):
            raise value
        return value

    def close(self) -> None:
        self.closes += 1


class Token:
    cancelled = True


def _request(*, context_generation: int = 1, model_generation: int = 1):
    return TranslationRequestBuilder().build(
        "привет Forge-11",
        source_language="ru",
        protected_terms=("Forge-11",),
        context_generation=context_generation,
        glossary_generation=2,
        model_generation=model_generation,
    )


def test_router_retries_transient_then_caches_by_all_generations() -> None:
    contextual = FakeProvider(
        "contextual",
        [TranslationProviderError("temporary", retryable=True), "hello Forge-11"],
    )
    router = TranslationRouter(contextual, None, timeout_seconds=0.25, maximum_attempts=2)
    first = router.translate(_request())
    assert first.result.natural_text == "hello Forge-11"
    assert first.attempts == 2
    assert router.translate(_request()) == first
    assert contextual.calls == 2
    router.translate(_request(context_generation=2))
    router.translate(_request(context_generation=2, model_generation=2))
    assert contextual.calls == 4


def test_router_falls_back_to_lightweight_then_original_with_visible_warning() -> None:
    contextual = FakeProvider("contextual", [TranslationTimedOut("timeout")])
    lightweight = FakeProvider("argos", ["hi Forge-11"])
    router = TranslationRouter(contextual, lightweight, timeout_seconds=0.25)
    fallback = router.translate(_request())
    assert fallback.degraded
    assert fallback.error_code == "TRANSLATION_LIGHTWEIGHT_FALLBACK"
    assert fallback.result.provider == "argos"
    assert fallback.result.warnings

    broken = TranslationRouter(
        FakeProvider("contextual", [TranslationProviderError("bad")]),
        FakeProvider("argos", [TranslationProviderError("also bad")]),
        timeout_seconds=0.25,
    ).translate(_request())
    assert broken.result.natural_text == "привет Forge-11"
    assert broken.result.provider == "untranslated"
    assert broken.error_code == "TRANSLATION_PROVIDER_FAILED"
    assert broken.result.warnings


def test_router_never_retries_cancellation_or_protected_term_corruption() -> None:
    cancelled_provider = FakeProvider("contextual", [TranslationCancelled("cancelled")])
    fallback = FakeProvider("argos", ["must not run Forge-11"])
    with pytest.raises(TranslationCancelled):
        TranslationRouter(cancelled_provider, fallback, timeout_seconds=0.25).translate(_request())
    assert fallback.calls == 0

    with pytest.raises(TranslationCancelled):
        TranslationRouter(
            FakeProvider("contextual", ["unused"]), None, timeout_seconds=0.25
        ).translate(_request(), Token())

    corrupt = FakeProvider("contextual", ["hello without protected term"])
    safe = FakeProvider("argos", ["hello Forge-11"])
    outcome = TranslationRouter(corrupt, safe, timeout_seconds=0.25).translate(_request())
    assert outcome.result.provider == "argos"


def test_router_close_is_safe_and_idempotent_for_distinct_providers() -> None:
    first = FakeProvider("one", ["ok"])
    second = FakeProvider("two", ["ok"])
    router = TranslationRouter(first, second)
    router.close()
    router.close()
    assert first.closes == 1 and second.closes == 1
