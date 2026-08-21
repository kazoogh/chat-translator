from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from game_chat_translator.capture.base import RawFrame
from game_chat_translator.models import ChatLine, OcrFragment
from game_chat_translator.vision.base import CancellationToken, OcrInput, OcrProvider
from game_chat_translator.vision.line_grouping import group_fragments
from game_chat_translator.vision.preprocess import PreprocessConfig, PreprocessedImage


class Preprocessor(Protocol):
    def process(self, frame: RawFrame, config: PreprocessConfig) -> PreprocessedImage: ...


@dataclass(frozen=True, slots=True)
class CalibrationPreview:
    processed: PreprocessedImage
    fragments: tuple[OcrFragment, ...]
    lines: tuple[ChatLine, ...]

    @property
    def has_likely_text(self) -> bool:
        return any(line.confidence >= 0.45 and line.normalized_text for line in self.lines)


class CalibrationPreviewService:
    """Worker-side preview pipeline; callers must not invoke it on the UI thread."""

    def __init__(self, preprocessor: Preprocessor, provider: OcrProvider) -> None:
        self._preprocessor = preprocessor
        self._provider = provider

    def run(
        self,
        frame: RawFrame,
        config: PreprocessConfig,
        *,
        generation: int,
        cancellation: CancellationToken | None = None,
    ) -> CalibrationPreview:
        processed = self._preprocessor.process(frame, config)
        request = OcrInput(
            processed.pixels,
            processed.width,
            processed.height,
            processed.channels,
            generation,
        )
        fragments = self._provider.recognize(request, cancellation)
        return CalibrationPreview(processed, fragments, group_fragments(fragments))
