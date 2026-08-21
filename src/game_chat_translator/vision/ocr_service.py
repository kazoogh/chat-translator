from __future__ import annotations

from contextlib import suppress
from threading import Event

from game_chat_translator.models import OcrFragment
from game_chat_translator.vision.base import (
    CancellationToken,
    OcrCancelled,
    OcrInput,
    OcrProvider,
    OcrProviderError,
    ProviderHealth,
)


class EventCancellationToken:
    def __init__(self, parent: CancellationToken | None = None) -> None:
        self._event = Event()
        self._parent = parent

    @property
    def cancelled(self) -> bool:
        return self._event.is_set() or (self._parent is not None and self._parent.cancelled)

    def cancel(self) -> None:
        self._event.set()


class OcrProviderRouter:
    def __init__(self, preferred: OcrProvider, cpu_fallback: OcrProvider) -> None:
        self._preferred = preferred
        self._cpu = cpu_fallback
        self._selected: OcrProvider | None = None

    @property
    def health(self) -> ProviderHealth:
        return self._selected.health if self._selected else ProviderHealth.UNINITIALIZED

    def health_check(self) -> bool:
        if _safe_health_check(self._preferred):
            self._selected = self._preferred
            return True
        if _safe_health_check(self._cpu):
            self._selected = self._cpu
            return True
        self._selected = None
        return False

    def recognize(
        self, request: OcrInput, cancellation: CancellationToken | None = None
    ) -> tuple[OcrFragment, ...]:
        if self._selected is None and not self.health_check():
            raise OcrProviderError("no OCR provider is healthy")
        assert self._selected is not None
        try:
            return self._selected.recognize(request, cancellation)
        except OcrCancelled:
            raise
        except Exception:
            if self._selected is self._cpu:
                raise OcrProviderError("CPU OCR provider failed") from None
            _safe_close(self._preferred)
            if not _safe_health_check(self._cpu):
                self._selected = None
                raise OcrProviderError("no OCR provider is healthy") from None
            self._selected = self._cpu
            try:
                return self._cpu.recognize(request, cancellation)
            except OcrCancelled:
                raise
            except Exception:
                raise OcrProviderError("CPU OCR provider failed") from None

    def close(self) -> None:
        _safe_close(self._preferred)
        if self._cpu is not self._preferred:
            _safe_close(self._cpu)
        self._selected = None


def _safe_health_check(provider: OcrProvider) -> bool:
    try:
        return provider.health_check()
    except Exception:
        return False


def _safe_close(provider: OcrProvider) -> None:
    with suppress(Exception):
        provider.close()
