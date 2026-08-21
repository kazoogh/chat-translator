from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from threading import Lock
from typing import Any

from game_chat_translator.language.base import LanguageProviderError
from game_chat_translator.validation.schemas import ModelEntry

_ALLOWED_LANGUAGES = frozenset({"en", "ru", "tr"})


class FastTextLanguageProvider:
    """Lazy, offline adapter for a checksummed fastText language-ID model."""

    def __init__(self, model_path: Path, *, manifest_entry: ModelEntry) -> None:
        self._source_path = model_path
        self._path = model_path.resolve()
        if manifest_entry.provider != "fasttext":
            raise ValueError("language model manifest entry must use the fastText provider")
        if not {"en", "ru", "tr"} <= set(manifest_entry.languages):
            raise ValueError("fastText language model must cover English, Russian, and Turkish")
        self._manifest_entry = manifest_entry
        self._model: Any | None = None
        self._lock = Lock()

    def predict(self, text: str) -> tuple[str, float]:
        bounded = " ".join(text[:8_192].splitlines()).strip()
        if not bounded:
            return "unknown", 0.0
        model = self._ensure_model()
        try:
            try:
                labels, scores = model.predict(bounded, k=3)
            except ValueError as exc:
                if "Unable to avoid copy" not in str(exc) or not hasattr(model, "f"):
                    raise
                predictions = model.f.predict(f"{bounded}\n", 3, 0.0, "strict")
                scores = [prediction[0] for prediction in predictions]
                labels = [prediction[1] for prediction in predictions]
            for label, score in zip(labels, scores, strict=False):
                language = str(label).removeprefix("__label__")
                if language in _ALLOWED_LANGUAGES:
                    return language, max(0.0, min(1.0, float(score)))
        except (RuntimeError, TypeError, ValueError) as exc:
            raise LanguageProviderError("local language identification failed") from exc
        return "unknown", 0.0

    def close(self) -> None:
        with self._lock:
            self._model = None

    def _ensure_model(self) -> Any:
        with self._lock:
            if self._model is not None:
                return self._model
            try:
                if (
                    self._source_path.is_symlink()
                    or not self._path.is_file()
                    or self._path.stat().st_size != self._manifest_entry.size_bytes
                    or self._path.stat().st_size > 1_073_741_824
                ):
                    raise LanguageProviderError("local language model is missing or invalid")
                with tempfile.TemporaryDirectory(prefix="gct-language-model-") as directory:
                    verified_copy = Path(directory) / "model.bin"
                    digest = hashlib.sha256()
                    with self._path.open("rb") as source, verified_copy.open("xb") as target:
                        for chunk in iter(lambda: source.read(1_048_576), b""):
                            digest.update(chunk)
                            target.write(chunk)
                        target.flush()
                        os.fsync(target.fileno())
                    if digest.hexdigest() != self._manifest_entry.sha256:
                        raise LanguageProviderError("local language model checksum does not match")
                    import fasttext

                    self._model = fasttext.load_model(str(verified_copy))
            except (ImportError, OSError, RuntimeError, ValueError) as exc:
                if isinstance(exc, LanguageProviderError):
                    raise
                raise LanguageProviderError("local language model could not be loaded") from exc
            return self._model
