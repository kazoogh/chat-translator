from __future__ import annotations

from game_chat_translator.translation import (
    BuiltinCorpusTranslationProvider,
    TranslationRequestBuilder,
    TranslationRouter,
)
from game_chat_translator.translation.base import TranslationProviderError


class _FailingProvider:
    model_id = None

    def __init__(self, provider_id: str) -> None:
        self.provider_id = provider_id

    def health_check(self) -> bool:
        return True

    def translate(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        raise TranslationProviderError("offline provider unavailable")

    def close(self) -> None:
        pass


def _request(source: str):  # type: ignore[no-untyped-def]
    return TranslationRequestBuilder().build(
        source,
        source_language="ru",
        context_generation=1,
        glossary_generation=1,
        model_generation=1,
    )


def test_reviewed_builtin_fallback_works_on_clean_install_without_native_models() -> None:
    source = "нахуй ты пкашишь долбаёб ебанный"
    router = TranslationRouter(
        _FailingProvider("contextual"),
        _FailingProvider("argos"),
        additional_fallbacks=(BuiltinCorpusTranslationProvider(),),
    )
    outcome = router.translate(_request(source))
    assert outcome.result.provider == "reviewed_corpus"
    assert outcome.result.natural_text == "why the fuck are you PKing, you stupid fucking idiot?"
    assert outcome.degraded


def test_unknown_phrase_still_returns_original_without_fabrication() -> None:
    source = "совершенно новая неизвестная фраза"
    outcome = TranslationRouter(
        None, BuiltinCorpusTranslationProvider(), timeout_seconds=0.25
    ).translate(_request(source))
    assert outcome.result.natural_text == source
    assert outcome.result.provider == "untranslated"
