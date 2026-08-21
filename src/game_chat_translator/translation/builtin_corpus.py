from __future__ import annotations

import json
import time
import unicodedata
from pathlib import Path

from game_chat_translator.resource_paths import bundled_resource_root
from game_chat_translator.translation.base import (
    CancellationToken,
    TranslationCancelled,
    TranslationProviderError,
    TranslationRequest,
    TranslationTimedOut,
)
from game_chat_translator.validation.schemas import CorpusRow


class BuiltinCorpusTranslationProvider:
    """Small, dependency-free fallback for exact reviewed phrase matches."""

    provider_id = "reviewed_corpus"
    model_id = "stalzone.translation.v1"

    def __init__(self, corpus_path: Path | None = None) -> None:
        root = bundled_resource_root()
        self._path = corpus_path or root / "data" / "corpora" / "stalzone.translation.v1.jsonl"
        self._translations: dict[str, str] | None = None

    def health_check(self) -> bool:
        try:
            return bool(self._load())
        except TranslationProviderError:
            return False

    def translate(
        self,
        request: TranslationRequest,
        *,
        timeout_seconds: float,
        cancellation: CancellationToken | None = None,
    ) -> str:
        if cancellation is not None and cancellation.cancelled:
            raise TranslationCancelled("translation was cancelled")
        started = time.monotonic()
        output = self._load().get(_normalize(request.source_text))
        if time.monotonic() - started > timeout_seconds:
            raise TranslationTimedOut("reviewed corpus lookup timed out")
        if output is None:
            raise TranslationProviderError("reviewed corpus has no exact translation")
        return output

    def close(self) -> None:
        self._translations = None

    def _load(self) -> dict[str, str]:
        if self._translations is not None:
            return self._translations
        if self._path.is_symlink() or not self._path.is_file():
            raise TranslationProviderError("reviewed translation corpus is unavailable")
        translations: dict[str, str] = {}
        try:
            with self._path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    row = CorpusRow.model_validate(json.loads(line))
                    if row.natural_english_meaning:
                        translations[_normalize(row.source_text)] = row.natural_english_meaning
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
            raise TranslationProviderError("reviewed translation corpus could not load") from exc
        self._translations = translations
        return translations


def _normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())
