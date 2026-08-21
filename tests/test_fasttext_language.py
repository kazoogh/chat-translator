from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from game_chat_translator.language.base import LanguageProviderError
from game_chat_translator.language.detector import LocalLanguageDetector
from game_chat_translator.language.fasttext_provider import FastTextLanguageProvider
from game_chat_translator.validation.schemas import ModelEntry


class _FakeModel:
    def predict(self, text: str, *, k: int) -> tuple[list[str], list[float]]:
        assert text == "attack base now"
        assert k == 3
        return ["__label__en", "__label__tr"], [0.91, 0.04]


def _entry(path: Path, digest: str) -> ModelEntry:
    return ModelEntry.model_validate(
        {
            "model_id": "language.test",
            "provider": "fasttext",
            "languages": ["en", "ru", "tr"],
            "hardware_tier": "cpu_low",
            "size_bytes": path.stat().st_size,
            "license_id": "test-only",
            "source_url": "https://example.invalid/language.test.bin",
            "sha256": digest,
        }
    )


def test_fasttext_provider_is_lazy_checksummed_and_improves_unknown_latin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model_path = tmp_path / "lid.ftz"
    model_path.write_bytes(b"local-model")
    digest = hashlib.sha256(model_path.read_bytes()).hexdigest()
    loaded: list[str] = []
    monkeypatch.setitem(
        sys.modules,
        "fasttext",
        SimpleNamespace(load_model=lambda path: loaded.append(path) or _FakeModel()),
    )
    provider = FastTextLanguageProvider(model_path, manifest_entry=_entry(model_path, digest))
    assert loaded == []
    analysis = LocalLanguageDetector(statistical_provider=provider).analyze("attack base now")
    assert analysis.primary_language == "en"
    assert analysis.confidence == pytest.approx(0.91)
    assert len(loaded) == 1
    assert Path(loaded[0]).name == "model.bin"
    assert Path(loaded[0]).parent != model_path.parent


def test_fasttext_provider_rejects_wrong_digest_without_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model_path = tmp_path / "lid.ftz"
    model_path.write_bytes(b"tampered")
    monkeypatch.delitem(sys.modules, "fasttext", raising=False)
    provider = FastTextLanguageProvider(model_path, manifest_entry=_entry(model_path, "0" * 64))
    with pytest.raises(LanguageProviderError, match="checksum"):
        provider.predict("hello")


@pytest.mark.language
def test_pinned_fasttext_wheel_trains_loads_and_predicts_locally(tmp_path: Path) -> None:
    import fasttext

    training = tmp_path / "language.txt"
    rows = []
    for _ in range(20):
        rows.extend(
            (
                "__label__en hello trade attack base now",
                "__label__ru привет торговля атака база сейчас",
                "__label__tr merhaba ticaret sald\u0131r\u0131 üs şimdi",
            )
        )
    training.write_text("\n".join(rows), encoding="utf-8")
    model = fasttext.train_supervised(
        input=str(training), epoch=10, dim=8, minn=2, maxn=4, verbose=0
    )
    model_path = tmp_path / "language.bin"
    model.save_model(str(model_path))
    digest = hashlib.sha256(model_path.read_bytes()).hexdigest()
    provider = FastTextLanguageProvider(model_path, manifest_entry=_entry(model_path, digest))
    language, confidence = provider.predict("hello trade now")
    assert language == "en"
    assert 0.0 <= confidence <= 1.0
