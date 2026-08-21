from __future__ import annotations

import time
from pathlib import Path
from threading import Lock
from typing import Any

from game_chat_translator.translation.base import (
    CancellationToken,
    TranslationCancelled,
    TranslationProviderError,
    TranslationRequest,
    TranslationTimedOut,
)


class LlamaCppTranslationProvider:
    """Lazy adapter for an explicitly installed local GGUF model."""

    provider_id = "llama_cpp"

    def __init__(
        self,
        model_path: Path,
        *,
        model_id: str,
        context_size: int = 2_048,
        maximum_output_tokens: int = 384,
    ) -> None:
        self._path = model_path.resolve()
        self._source_path = model_path
        self.model_id = model_id
        self._context_size = context_size
        self._maximum_output_tokens = maximum_output_tokens
        self._model: Any | None = None
        self._lock = Lock()

    def health_check(self) -> bool:
        try:
            self._ensure_model()
        except TranslationProviderError:
            return False
        return True

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
        model = self._ensure_model()
        try:
            with self._lock:
                response = model(
                    request.prompt,
                    max_tokens=self._maximum_output_tokens,
                    temperature=0.2,
                    stop=("\nSOURCE:",),
                )
            output = str(response["choices"][0]["text"]).strip()
        except (KeyError, IndexError, RuntimeError, TypeError, ValueError) as exc:
            raise TranslationProviderError("local contextual translation failed") from exc
        if cancellation is not None and cancellation.cancelled:
            raise TranslationCancelled("translation was cancelled")
        if time.monotonic() - started > timeout_seconds:
            raise TranslationTimedOut("local contextual translation timed out")
        return output

    def close(self) -> None:
        with self._lock:
            self._model = None

    def _ensure_model(self) -> Any:
        with self._lock:
            if self._model is not None:
                return self._model
            if self._source_path.is_symlink() or not self._path.is_file():
                raise TranslationProviderError("local contextual model is missing")
            try:
                from llama_cpp import Llama

                self._model = Llama(
                    model_path=str(self._path), n_ctx=self._context_size, verbose=False
                )
            except (ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
                raise TranslationProviderError("local contextual model could not load") from exc
            return self._model
