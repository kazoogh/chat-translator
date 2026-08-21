from __future__ import annotations

from typing import Protocol


class LanguageProviderError(RuntimeError):
    pass


class StatisticalLanguageProvider(Protocol):
    def predict(self, text: str) -> tuple[str, float]: ...

    def close(self) -> None: ...
