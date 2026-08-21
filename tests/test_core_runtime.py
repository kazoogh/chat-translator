from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from game_chat_translator.core_runtime import CoreRuntime
from game_chat_translator.runtime.queues import OfferResult
from game_chat_translator.translation import TranslationJob, TranslationRequestBuilder
from game_chat_translator.translation.base import (
    CancellationToken,
    TranslationProviderError,
    TranslationRequest,
)


@dataclass
class _Response:
    payload: bytes
    final_url: str
    total_size: int
    supports_resume: bool = True

    def chunks(self, _size: int):  # type: ignore[no-untyped-def]
        yield self.payload

    def close(self) -> None:
        pass


class _Source:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def open(self, url: str, *, offset: int) -> _Response:
        return _Response(self.payload[offset:], url, len(self.payload))


class _Provider:
    provider_id = "fixture"
    model_id = "fixture-model"

    def __init__(self, *, fails: bool = False) -> None:
        self._fails = fails

    def health_check(self) -> bool:
        return True

    def translate(
        self,
        request: TranslationRequest,
        *,
        timeout_seconds: float,
        cancellation: CancellationToken | None = None,
    ) -> str:
        del timeout_seconds, cancellation
        if self._fails:
            raise TranslationProviderError("fixture fallback unavailable")
        return f"translated:{request.source_text}"

    def close(self) -> None:
        pass


def _resource_root(tmp_path: Path, payload: bytes) -> Path:
    root = tmp_path / "resources"
    path = root / "data" / "models"
    path.mkdir(parents=True)
    manifest = {
        "schema_version": 1,
        "models": [
            {
                "model_id": "fixture-model",
                "provider": "llama_cpp",
                "languages": ["en", "ru", "tr"],
                "hardware_tier": "cpu_low",
                "size_bytes": len(payload),
                "license_id": "test-only",
                "source_url": "https://models.example.invalid/fixture.gguf",
                "sha256": hashlib.sha256(payload).hexdigest(),
                "bundled": False,
            }
        ],
    }
    (path / "manifest.v1.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


def test_explicit_setup_restart_translate_and_remove_composition(tmp_path: Path) -> None:
    payload = b"healthy-fixture-model"
    resources = _resource_root(tmp_path, payload)
    state = tmp_path / "state.sqlite3"
    models = tmp_path / "models"
    common = {
        "resource_root": resources,
        "state_path": state,
        "model_root": models,
        "source": _Source(payload),
        "model_health_check": lambda _entry, path: path.read_bytes() == payload,
        "contextual_factory": lambda _entry, _path: _Provider(),
        "lightweight_factory": lambda: _Provider(fails=True),
    }
    with CoreRuntime(**common) as setup:  # type: ignore[arg-type]
        options = setup.model_options()
        assert not options[0].installed
        progress: list[tuple[int, int]] = []
        outcome = setup.download_model(
            "fixture-model", progress=lambda a, b: progress.append((a, b))
        )
        assert outcome.code == "ACTIVATED"
        assert progress[-1] == (len(payload), len(payload))

    with CoreRuntime(**common) as restarted:  # type: ignore[arg-type]
        assert restarted.model_options()[0].installed
        pipeline = restarted.build_translation_pipeline(
            model_id="fixture-model", initial_generations=(1, 1, 1, 1, 1, 1)
        )
        request = TranslationRequestBuilder().build(
            "привет",
            source_language="ru",
            context_generation=1,
            glossary_generation=1,
            model_generation=1,
        )
        assert pipeline.offer(TranslationJob(uuid4(), request, 1, 1, 1)) is OfferResult.ACCEPTED
        assert pipeline.process_next() is OfferResult.ACCEPTED
        assert pipeline.take().outcome.result.natural_text == "translated:привет"  # type: ignore[union-attr]
        assert restarted.remove_model("fixture-model").code == "MODEL_IN_USE"
        restarted.release_pipeline(pipeline)
        assert restarted.remove_model("fixture-model").code == "REMOVED"

    with CoreRuntime(**common) as final:  # type: ignore[arg-type]
        assert not final.model_options()[0].installed


def test_model_remains_in_use_until_every_pipeline_releases_it(tmp_path: Path) -> None:
    payload = b"healthy-fixture-model"
    resources = _resource_root(tmp_path, payload)
    arguments = {
        "resource_root": resources,
        "state_path": tmp_path / "state.sqlite3",
        "model_root": tmp_path / "models",
        "source": _Source(payload),
        "model_health_check": lambda _entry, path: path.read_bytes() == payload,
        "contextual_factory": lambda _entry, _path: _Provider(),
        "lightweight_factory": lambda: _Provider(fails=True),
    }
    with CoreRuntime(**arguments) as runtime:  # type: ignore[arg-type]
        assert runtime.download_model("fixture-model").code == "ACTIVATED"
        first = runtime.build_translation_pipeline(model_id="fixture-model")
        second = runtime.build_translation_pipeline(model_id="fixture-model")
        runtime.release_pipeline(first)
        assert runtime.remove_model("fixture-model").code == "MODEL_IN_USE"
        assert (tmp_path / "models" / "fixture-model.bin").is_file()
        runtime.release_pipeline(second)
        assert runtime.remove_model("fixture-model").code == "REMOVED"
