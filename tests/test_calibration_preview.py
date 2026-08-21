from __future__ import annotations

from dataclasses import dataclass

from game_chat_translator.capture.base import RawFrame
from game_chat_translator.models import OcrFragment, Point
from game_chat_translator.vision.base import OcrInput, ProviderHealth
from game_chat_translator.vision.calibration_preview import CalibrationPreviewService
from game_chat_translator.vision.preprocess import PreprocessConfig, ReferencePreprocessor


@dataclass
class PreviewProvider:
    health: ProviderHealth = ProviderHealth.READY

    def health_check(self) -> bool:
        return True

    def recognize(self, request: OcrInput, cancellation: object = None) -> tuple[OcrFragment, ...]:
        del cancellation
        assert request.channels == 1
        return (
            OcrFragment(
                text="Игрок: привет",
                confidence=0.95,
                polygon=(Point(x=0, y=0), Point(x=8, y=0), Point(x=8, y=4), Point(x=0, y=4)),
                script="cyrillic",
            ),
        )

    def close(self) -> None:
        self.health = ProviderHealth.STOPPED


def test_calibration_preview_runs_preprocess_ocr_grouping_in_memory() -> None:
    frame = RawFrame(2, 2, "BGRA", bytes((255, 255, 255, 255) * 4))
    preview = CalibrationPreviewService(ReferencePreprocessor(), PreviewProvider()).run(
        frame, PreprocessConfig(scale=2, sharpen=False), generation=7
    )
    assert preview.processed.width == 4
    assert preview.lines[0].raw_text == "Игрок: привет"
    assert preview.has_likely_text
