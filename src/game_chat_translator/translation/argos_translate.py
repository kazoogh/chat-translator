from __future__ import annotations

import time
from threading import Lock
from typing import Any

from game_chat_translator.translation.base import (
    CancellationToken,
    TranslationCancelled,
    TranslationProviderError,
    TranslationRequest,
    TranslationTimedOut,
)


class ArgosTranslationProvider:
    """Lazy adapter using only already-installed Argos language packages."""

    provider_id = "argos"
    model_id = None

    def __init__(self) -> None:
        self._translate_module: Any | None = None
        self._lock = Lock()

    def health_check(self) -> bool:
        try:
            return bool(self._installed_languages())
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
        languages = self._installed_languages()
        source = next((item for item in languages if item.code == request.source_language), None)
        target = next((item for item in languages if item.code == request.target_language), None)
        if source is None or target is None:
            raise TranslationProviderError("required offline Argos language package is missing")
        try:
            translation = source.get_translation(target)
            with self._lock:
                output = str(translation.translate(request.source_text)).strip()
        except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
            raise TranslationProviderError("lightweight offline translation failed") from exc
        if cancellation is not None and cancellation.cancelled:
            raise TranslationCancelled("translation was cancelled")
        if time.monotonic() - started > timeout_seconds:
            raise TranslationTimedOut("lightweight offline translation timed out")
        return output

    def close(self) -> None:
        with self._lock:
            self._translate_module = None

    def _installed_languages(self) -> list[Any]:
        if self._translate_module is None:
            try:
                import argostranslate.translate

                self._translate_module = argostranslate.translate
            except ImportError as exc:
                raise TranslationProviderError("Argos Translate is not installed") from exc
        try:
            return list(self._translate_module.get_installed_languages())
        except (RuntimeError, TypeError, ValueError) as exc:
            raise TranslationProviderError("installed Argos packages could not be read") from exc
