from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from game_chat_translator.models import CapturedFrame, ChatRegion, OcrFragment, Point
from game_chat_translator.runtime.queues import OfferResult
from game_chat_translator.vision.base import (
    CancellationToken,
    OcrInput,
    OcrOutcome,
    OcrProviderError,
    ProviderHealth,
)
from game_chat_translator.vision.line_tracker import LineTracker
from game_chat_translator.vision.pipeline import FrameWork, OcrPipeline, PipelineUpdate
from game_chat_translator.vision.preprocess import PreprocessConfig, ReferencePreprocessor


class PipelineProvider:
    def __init__(self, *, fail: bool = False) -> None:
        self.health = ProviderHealth.READY
        self.fail = fail

    def health_check(self) -> bool:
        return True

    def recognize(self, request: OcrInput, cancellation: object = None) -> tuple[OcrFragment, ...]:
        del request, cancellation
        if self.fail:
            raise OcrProviderError("raw provider detail must remain internal")
        return (
            OcrFragment(
                text="Player: привет",
                confidence=0.95,
                polygon=(Point(x=0, y=0), Point(x=8, y=0), Point(x=8, y=4), Point(x=0, y=4)),
                script="mixed",
            ),
        )

    def close(self) -> None:
        self.health = ProviderHealth.STOPPED


class SequenceProvider(PipelineProvider):
    def __init__(self, texts: list[str]) -> None:
        super().__init__()
        self._texts = iter(texts)

    def recognize(self, request: OcrInput, cancellation: object = None) -> tuple[OcrFragment, ...]:
        del request, cancellation
        text = next(self._texts)
        return (
            OcrFragment(
                text=text,
                confidence=0.95,
                polygon=(Point(x=0, y=0), Point(x=8, y=0), Point(x=8, y=4), Point(x=0, y=4)),
                script="latin",
            ),
        )


class DirectTestService:
    def __init__(self, provider: PipelineProvider) -> None:
        self.provider = provider

    def recognize(
        self,
        request: OcrInput,
        *,
        generation: Callable[[], int],
        cancellation: CancellationToken | None = None,
    ) -> OcrOutcome:
        del generation
        try:
            fragments = self.provider.recognize(request, cancellation)
        except OcrProviderError:
            return OcrOutcome(
                (), ProviderHealth.DEGRADED, request.generation, "OCR_PROVIDER_FAILED"
            )
        return OcrOutcome(fragments, ProviderHealth.READY, request.generation)

    def close(self) -> None:
        self.provider.close()


def _frame(value: int = 255) -> CapturedFrame:
    return CapturedFrame(
        captured_at=datetime.now(UTC),
        monotonic_seconds=1.0,
        profile_id="test.game",
        layout_id="layout",
        region=ChatRegion(
            x=0,
            y=0,
            width=0.5,
            height=0.5,
            layout_id="layout",
            reference_client_width=100,
            reference_client_height=100,
            reference_dpi=96,
        ),
        width=2,
        height=2,
        pixels=bytes((value, value, value, 255) * 4),
    )


def test_integrated_pipeline_replaces_stale_frame_and_publishes_tracked_lines() -> None:
    updates: list[PipelineUpdate] = []
    pipeline = OcrPipeline(
        ReferencePreprocessor(),
        DirectTestService(PipelineProvider()),
        LineTracker(),
        initial_generation=1,
        publish_status=updates.append,
    )
    config = PreprocessConfig(scale=1, sharpen=False)
    assert pipeline.submit(FrameWork(_frame(1), config, 1)) is OfferResult.ACCEPTED
    assert pipeline.submit(FrameWork(_frame(2), config, 1)) is OfferResult.REPLACED_STALE
    update = pipeline.process_next()
    assert update == PipelineUpdate(ProviderHealth.READY, 1, 1)
    result = pipeline.take_result()
    assert result is not None
    assert result.lines[0].raw_text == "Player: привет"
    assert updates == [update]
    pipeline.close()


def test_pipeline_failure_is_safe_visible_and_does_not_publish_content() -> None:
    updates: list[PipelineUpdate] = []
    pipeline = OcrPipeline(
        ReferencePreprocessor(),
        DirectTestService(PipelineProvider(fail=True)),
        LineTracker(),
        initial_generation=4,
        publish_status=updates.append,
    )
    pipeline.submit(FrameWork(_frame(), PreprocessConfig(scale=1, sharpen=False), 4))
    update = pipeline.process_next()
    assert update is not None
    assert update.error_code == "OCR_PROVIDER_FAILED"
    assert "Player" not in repr(update)
    assert pipeline.take_result() is None
    pipeline.close()


def test_pipeline_generation_change_purges_frames_and_results() -> None:
    pipeline = OcrPipeline(
        ReferencePreprocessor(),
        DirectTestService(PipelineProvider()),
        LineTracker(),
        initial_generation=7,
        publish_status=lambda update: None,
    )
    work = FrameWork(_frame(), PreprocessConfig(scale=1, sharpen=False), 7)
    pipeline.submit(work)
    pipeline.advance_generation(8)
    assert pipeline.process_next() is None
    assert pipeline.submit(work) is OfferResult.REJECTED_OBSOLETE
    pipeline.close()


def test_result_backpressure_preserves_new_line_until_capacity_is_available() -> None:
    pipeline = OcrPipeline(
        ReferencePreprocessor(),
        DirectTestService(SequenceProvider(["one", "two", "three"])),
        LineTracker(),
        initial_generation=1,
        publish_status=lambda update: None,
    )
    config = PreprocessConfig(scale=1, sharpen=False)
    for _ in range(2):
        pipeline.submit(FrameWork(_frame(), config, 1))
        assert pipeline.process_next() is not None
    pipeline.submit(FrameWork(_frame(), config, 1))
    blocked = pipeline.process_next()
    assert blocked is not None
    assert blocked.error_code == "OCR_RESULTS_BACKPRESSURE"

    first = pipeline.take_result()
    assert first is not None and first.lines[0].raw_text == "one"
    flushed = pipeline.process_next()
    assert flushed == PipelineUpdate(ProviderHealth.READY, 1, 1)
    second = pipeline.take_result()
    third = pipeline.take_result()
    assert second is not None and second.lines[0].raw_text == "two"
    assert third is not None and third.lines[0].raw_text == "three"
    assert pipeline.process_next() is None
    pipeline.close()


def test_static_frame_does_not_consume_result_queue_capacity() -> None:
    pipeline = OcrPipeline(
        ReferencePreprocessor(),
        DirectTestService(SequenceProvider(["same", "same"])),
        LineTracker(),
        initial_generation=1,
        publish_status=lambda update: None,
    )
    config = PreprocessConfig(scale=1, sharpen=False)
    for _ in range(2):
        pipeline.submit(FrameWork(_frame(), config, 1))
        pipeline.process_next()
    assert pipeline.take_result() is not None
    assert pipeline.take_result() is None
    pipeline.close()


def test_generation_change_after_service_success_cannot_mutate_old_tracker_state() -> None:
    holder: list[OcrPipeline] = []

    class SwitchingService(DirectTestService):
        def recognize(
            self,
            request: OcrInput,
            *,
            generation: Callable[[], int],
            cancellation: CancellationToken | None = None,
        ) -> OcrOutcome:
            outcome = super().recognize(request, generation=generation, cancellation=cancellation)
            holder[0].advance_generation(2)
            return outcome

    pipeline = OcrPipeline(
        ReferencePreprocessor(),
        SwitchingService(SequenceProvider(["old", "new"])),
        LineTracker(),
        initial_generation=1,
        publish_status=lambda update: None,
    )
    holder.append(pipeline)
    config = PreprocessConfig(scale=1, sharpen=False)
    pipeline.submit(FrameWork(_frame(), config, 1))
    obsolete = pipeline.process_next()
    assert obsolete is not None and obsolete.error_code == "OCR_OBSOLETE_GENERATION"
    pipeline.submit(FrameWork(_frame(), config, 2))
    assert pipeline.process_next() == PipelineUpdate(ProviderHealth.READY, 2, 1)
    result = pipeline.take_result()
    assert result is not None and result.lines[0].raw_text == "new"
    pipeline.close()
