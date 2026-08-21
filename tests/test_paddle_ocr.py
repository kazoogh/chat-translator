from __future__ import annotations

import sys
from pathlib import Path
from threading import Barrier, Lock, Thread
from types import ModuleType

import pytest

from game_chat_translator.vision.base import OcrProviderError
from game_chat_translator.vision.paddle_ocr import (
    PaddleOcrConfig,
    PaddleOcrProvider,
    parse_paddle_v3_results,
)


class FakeV3Result:
    def __init__(self, payload: object) -> None:
        self.json = payload


def test_parse_paddle_3_result_contract_and_scripts() -> None:
    result = FakeV3Result(
        {
            "res": {
                "rec_texts": ["Привет", "Player42", "mixЖ", "low"],
                "rec_scores": [0.98, 0.91, 0.88, 0.2],
                "rec_polys": [
                    [[0, 0], [10, 0], [10, 5], [0, 5]],
                    [[0, 6], [10, 6], [10, 11], [0, 11]],
                    [[0, 12], [10, 12], [10, 17], [0, 17]],
                    [[0, 18], [10, 18], [10, 23], [0, 23]],
                ],
            }
        }
    )

    fragments = parse_paddle_v3_results([result], minimum_confidence=0.45)

    assert [fragment.text for fragment in fragments] == ["Привет", "Player42", "mixЖ"]
    assert [fragment.script for fragment in fragments] == ["cyrillic", "latin", "mixed"]


def test_parse_paddle_3_rejects_obsolete_or_inconsistent_shape() -> None:
    with pytest.raises(OcrProviderError, match="inconsistent lengths"):
        parse_paddle_v3_results(
            {"res": {"rec_texts": ["one"], "rec_scores": [], "rec_polys": []}},
            minimum_confidence=0.0,
        )
    with pytest.raises(OcrProviderError, match="JSON data"):
        parse_paddle_v3_results([[["PaddleOCR 2.x shape"]]], minimum_confidence=0.0)

    with pytest.raises(OcrProviderError, match="safe length"):
        parse_paddle_v3_results(
            {
                "res": {
                    "rec_texts": ["x" * 4_097],
                    "rec_scores": [1.0],
                    "rec_polys": [[[0, 0], [1, 0], [1, 1], [0, 1]]],
                }
            },
            minimum_confidence=0.0,
        )

    with pytest.raises(OcrProviderError, match="safe range"):
        parse_paddle_v3_results(
            {
                "res": {
                    "rec_texts": ["bad"],
                    "rec_scores": [float("nan")],
                    "rec_polys": [[[0, 0], [1, 0], [1, 1], [0, 1]]],
                }
            },
            minimum_confidence=0.0,
        )


def test_parse_paddle_3_accepts_a_bounded_result_generator() -> None:
    results = (
        item
        for item in [
            {
                "res": {
                    "rec_texts": ["generator"],
                    "rec_scores": [0.9],
                    "rec_polys": [[[0, 0], [1, 0], [1, 1], [0, 1]]],
                }
            }
        ]
    )
    assert parse_paddle_v3_results(results, minimum_confidence=0.0)[0].text == "generator"


def test_paddle_config_requires_explicit_local_model_directories(tmp_path: Path) -> None:
    detection = tmp_path / "detection"
    recognition = tmp_path / "recognition"
    detection.mkdir()
    recognition.mkdir()
    config = PaddleOcrConfig(detection, recognition)
    assert config.device == "cpu"

    with pytest.raises(ValueError, match="model directory is missing"):
        PaddleOcrConfig(tmp_path / "missing", recognition)

    provider = PaddleOcrProvider(config)
    assert provider.health_check() is False
    assert provider.health.value == "failed"


def test_paddle_initialization_disables_auxiliary_models_and_uses_local_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GCT_OCR_ISOLATED", "1")
    detection = tmp_path / "detection"
    recognition = tmp_path / "recognition"
    detection.mkdir()
    recognition.mkdir()
    received: dict[str, object] = {}

    class FakePaddleOcr:
        def __init__(self, **kwargs: object) -> None:
            received.update(kwargs)

    fake_module = ModuleType("paddleocr")
    fake_module.PaddleOCR = FakePaddleOcr  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "paddleocr", fake_module)

    provider = PaddleOcrProvider(PaddleOcrConfig(detection, recognition, device="gpu:0"))
    assert provider.health_check()
    assert received["device"] == "gpu:0"
    assert received["text_detection_model_dir"] == str(detection)
    assert received["text_recognition_model_dir"] == str(recognition)
    assert received["use_doc_orientation_classify"] is False
    assert received["use_doc_unwarping"] is False
    assert received["use_textline_orientation"] is False


def test_paddle_pipeline_initializes_once_under_concurrent_health_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GCT_OCR_ISOLATED", "1")
    detection = tmp_path / "detection"
    recognition = tmp_path / "recognition"
    detection.mkdir()
    recognition.mkdir()
    barrier = Barrier(4)
    count = 0
    count_lock = Lock()

    class FakePaddleOcr:
        def __init__(self, **kwargs: object) -> None:
            del kwargs
            nonlocal count
            with count_lock:
                count += 1

    fake_module = ModuleType("paddleocr")
    fake_module.PaddleOCR = FakePaddleOcr  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "paddleocr", fake_module)
    provider = PaddleOcrProvider(PaddleOcrConfig(detection, recognition))
    outcomes: list[bool] = []

    def check() -> None:
        barrier.wait()
        outcomes.append(provider.health_check())

    threads = [Thread(target=check) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert outcomes == [True] * 4
    assert count == 1
