from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from game_chat_translator.application import ApplicationController, InboundPresentationService
from game_chat_translator.application_pipeline import ApplicationPipelineCoordinator
from game_chat_translator.classification.classifier import MessageClassifier
from game_chat_translator.classification.pipeline import ClassificationPipeline
from game_chat_translator.language.detector import LocalLanguageDetector
from game_chat_translator.models import CapturedFrame, ChatRegion, OcrFragment, Point
from game_chat_translator.profiles.resources import ResourceRegistry
from game_chat_translator.settings import AppSettings
from game_chat_translator.translation import TranslationPipeline, TranslationRouter
from game_chat_translator.translation.base import CancellationToken, TranslationRequest
from game_chat_translator.ui.event_queue import PresentedMessage, UiEventKind, UiEventQueue
from game_chat_translator.vision.base import OcrInput, OcrOutcome, ProviderHealth
from game_chat_translator.vision.line_tracker import LineTracker
from game_chat_translator.vision.pipeline import OcrPipeline
from game_chat_translator.vision.preprocess import PreprocessConfig, ReferencePreprocessor

ROOT = Path(__file__).resolve().parents[1]


class _OcrService:
    def __init__(self, texts: tuple[str, ...]) -> None:
        self._texts = iter(texts)

    def recognize(
        self,
        request: OcrInput,
        *,
        generation: Callable[[], int],
        cancellation: CancellationToken | None = None,
    ) -> OcrOutcome:
        del generation, cancellation
        text = next(self._texts)
        fragment = OcrFragment(
            text=text,
            confidence=0.98,
            polygon=(Point(x=0, y=0), Point(x=8, y=0), Point(x=8, y=4), Point(x=0, y=4)),
            script="mixed",
        )
        return OcrOutcome((fragment,), ProviderHealth.READY, request.generation)

    def close(self) -> None:
        pass


class _Translator:
    provider_id = "fixture"
    model_id = "fixture-v1"

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
        return f"English: {request.source_text}"

    def close(self) -> None:
        pass


def _frame(index: int) -> CapturedFrame:
    return CapturedFrame(
        captured_at=datetime.now(UTC),
        monotonic_seconds=float(index),
        profile_id="stalzone.default",
        layout_id="default",
        region=ChatRegion(
            x=0,
            y=0,
            width=0.5,
            height=0.5,
            layout_id="default",
            reference_client_width=100,
            reference_client_height=100,
            reference_dpi=96,
        ),
        width=2,
        height=2,
        pixels=bytes((255, 255, 255, 255) * 4),
    )


def test_synthetic_frames_reach_display_and_speech_exactly_once_in_order() -> None:
    texts = ("Vasya: привет", "Petya: спасибо", "Olga: пока")
    events = UiEventQueue()
    spoken: list[PresentedMessage] = []
    application = ApplicationController(AppSettings(), events, queue_speech=spoken.append)
    application.start()
    resources = ResourceRegistry(ROOT).load_all()["stalzone.default"]
    coordinator = ApplicationPipelineCoordinator(
        OcrPipeline(
            ReferencePreprocessor(),
            _OcrService(texts),
            LineTracker(),
            initial_generation=1,
            publish_status=lambda _update: None,
        ),
        ClassificationPipeline(
            MessageClassifier(resources),
            LocalLanguageDetector(),
            initial_generation=1,
        ),
        TranslationPipeline(
            TranslationRouter(_Translator(), None),
            initial_generations=(1, 1, 1, 1, 1, 1),
        ),
        InboundPresentationService(application),
    )
    preprocess = PreprocessConfig(scale=1, sharpen=False)
    for index in range(3):
        coordinator.submit_frame(_frame(index + 1), preprocess, generation=1)
        assert coordinator.process_once()

    displayed = [event.payload for event in events.drain() if event.kind is UiEventKind.MESSAGE]
    assert [message.source_text for message in displayed] == ["привет", "спасибо", "пока"]
    assert [message.message_id for message in spoken] == [
        message.message_id for message in displayed
    ]
    coordinator.close()
