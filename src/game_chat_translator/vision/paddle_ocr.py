from __future__ import annotations

import math
import os
import threading
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import islice
from pathlib import Path
from typing import Any

from game_chat_translator.models import OcrFragment, Point
from game_chat_translator.vision.base import (
    CancellationToken,
    OcrCancelled,
    OcrInput,
    OcrProviderError,
    ProviderHealth,
)


@dataclass(frozen=True, slots=True)
class PaddleOcrConfig:
    detection_model_dir: Path
    recognition_model_dir: Path
    language: str = "ru"
    device: str = "cpu"
    minimum_confidence: float = 0.45

    def __post_init__(self) -> None:
        if self.device != "cpu" and not self.device.startswith("gpu"):
            raise ValueError("PaddleOCR device must be cpu or gpu[:index]")
        if not 0.0 <= self.minimum_confidence <= 1.0:
            raise ValueError("minimum OCR confidence must be between zero and one")
        for directory in (self.detection_model_dir, self.recognition_model_dir):
            if not directory.is_dir():
                raise ValueError(f"OCR model directory is missing: {directory.name}")


class PaddleOcrProvider:
    """PaddleOCR 3.x `predict()` adapter using explicitly installed local models."""

    def __init__(self, config: PaddleOcrConfig) -> None:
        self.config = config
        self._pipeline: Any = None
        self._health = ProviderHealth.UNINITIALIZED
        self._lock = threading.RLock()

    @property
    def health(self) -> ProviderHealth:
        return self._health

    def health_check(self) -> bool:
        try:
            self._ensure_pipeline()
        except OcrProviderError:
            return False
        return True

    def recognize(
        self, request: OcrInput, cancellation: CancellationToken | None = None
    ) -> tuple[OcrFragment, ...]:
        if cancellation is not None and cancellation.cancelled:
            raise OcrCancelled("OCR request was cancelled")
        try:
            import numpy as np

            shape: tuple[int, ...] = (request.height, request.width)
            if request.channels > 1:
                shape = (*shape, request.channels)
            with self._lock:
                pipeline = self._ensure_pipeline()
                image = np.frombuffer(request.pixels, dtype=np.uint8).reshape(shape)
                results = pipeline.predict(input=image)
            fragments = parse_paddle_v3_results(
                results, minimum_confidence=self.config.minimum_confidence
            )
        except OcrCancelled:
            raise
        except OcrProviderError:
            self._health = ProviderHealth.DEGRADED
            raise
        except (ImportError, RuntimeError, TypeError, ValueError, KeyError) as exc:
            self._health = ProviderHealth.DEGRADED
            raise OcrProviderError("PaddleOCR inference failed") from exc
        if cancellation is not None and cancellation.cancelled:
            raise OcrCancelled("OCR request was cancelled")
        self._health = ProviderHealth.READY
        return fragments

    def close(self) -> None:
        with self._lock:
            self._pipeline = None
            self._health = ProviderHealth.STOPPED

    def _ensure_pipeline(self) -> Any:
        with self._lock:
            if os.environ.get("GCT_OCR_ISOLATED") != "1":
                self._health = ProviderHealth.FAILED
                raise OcrProviderError("PaddleOCR must run in the isolated offline worker")
            if self._pipeline is not None:
                return self._pipeline
            if self._health is ProviderHealth.STOPPED:
                raise OcrProviderError("PaddleOCR provider is stopped")
            self._health = ProviderHealth.LOADING
            try:
                from paddleocr import PaddleOCR

                self._pipeline = PaddleOCR(
                    lang=self.config.language,
                    device=self.config.device,
                    text_detection_model_dir=str(self.config.detection_model_dir),
                    text_recognition_model_dir=str(self.config.recognition_model_dir),
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                    use_textline_orientation=False,
                )
            except (ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
                self._health = ProviderHealth.FAILED
                raise OcrProviderError("PaddleOCR could not initialize local models") from exc
            self._health = ProviderHealth.READY
            return self._pipeline


def parse_paddle_v3_results(results: Any, *, minimum_confidence: float) -> tuple[OcrFragment, ...]:
    if not 0.0 <= minimum_confidence <= 1.0:
        raise ValueError("minimum OCR confidence must be between zero and one")
    fragments: list[OcrFragment] = []
    for result in _as_results(results):
        payload = _result_payload(result)
        texts = payload.get("rec_texts", ())
        scores = payload.get("rec_scores", ())
        polygons = payload.get("rec_polys", payload.get("dt_polys", ()))
        if not all(_is_sequence_like(value) for value in (texts, scores, polygons)):
            raise OcrProviderError("PaddleOCR 3.x returned an invalid result schema")
        if not (len(texts) == len(scores) == len(polygons)):
            raise OcrProviderError("PaddleOCR 3.x result arrays have inconsistent lengths")
        if len(texts) > 512:
            raise OcrProviderError("PaddleOCR 3.x result exceeds the fragment limit")
        for text, score, polygon in zip(texts, scores, polygons, strict=True):
            confidence = float(score)
            if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
                raise OcrProviderError("PaddleOCR confidence is outside the safe range")
            rendered = str(text).strip()
            if len(rendered) > 4_096:
                raise OcrProviderError("PaddleOCR text exceeds the safe length limit")
            if not rendered or confidence < minimum_confidence:
                continue
            fragments.append(
                OcrFragment(
                    text=rendered,
                    confidence=confidence,
                    polygon=_polygon(polygon),
                    script=_script(rendered),
                )
            )
            if len(fragments) > 512:
                raise OcrProviderError("PaddleOCR 3.x result exceeds the fragment limit")
    return tuple(fragments)


def _as_results(results: Any) -> Sequence[Any]:
    if isinstance(results, Sequence) and not isinstance(results, str | bytes | Mapping):
        if len(results) > 32:
            raise OcrProviderError("PaddleOCR returned too many result pages")
        return results
    if isinstance(results, Iterable) and not isinstance(results, str | bytes | Mapping):
        materialized = tuple(islice(results, 33))
        if len(materialized) > 32:
            raise OcrProviderError("PaddleOCR returned too many result pages")
        return materialized
    return (results,)


def _is_sequence_like(value: Any) -> bool:
    return (
        not isinstance(value, str | bytes | Mapping)
        and hasattr(value, "__len__")
        and hasattr(value, "__iter__")
    )


def _result_payload(result: Any) -> Mapping[str, Any]:
    candidate = result if isinstance(result, Mapping) else getattr(result, "json", None)
    if not isinstance(candidate, Mapping):
        raise OcrProviderError("PaddleOCR 3.x result does not expose JSON data")
    payload = candidate.get("res", candidate)
    if not isinstance(payload, Mapping):
        raise OcrProviderError("PaddleOCR 3.x result payload is invalid")
    return payload


def _polygon(value: Any) -> tuple[Point, Point, Point, Point]:
    try:
        points = tuple(Point(x=float(item[0]), y=float(item[1])) for item in value)
    except (TypeError, ValueError, IndexError) as exc:
        raise OcrProviderError("PaddleOCR polygon is invalid") from exc
    if len(points) != 4:
        raise OcrProviderError("PaddleOCR polygon must contain four points")
    if any(not math.isfinite(coordinate) for point in points for coordinate in (point.x, point.y)):
        raise OcrProviderError("PaddleOCR polygon contains a non-finite coordinate")
    return points


def _script(text: str) -> str:
    has_cyrillic = any("CYRILLIC" in _unicode_name(character) for character in text)
    has_latin = any("LATIN" in _unicode_name(character) for character in text)
    if has_cyrillic and has_latin:
        return "mixed"
    if has_cyrillic:
        return "cyrillic"
    if has_latin:
        return "latin"
    return "unknown"


def _unicode_name(character: str) -> str:
    import unicodedata

    return unicodedata.name(character, "")
