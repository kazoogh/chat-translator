from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock
from typing import Protocol

from game_chat_translator.capture.base import RawFrame
from game_chat_translator.models import CapturedFrame, ChatLine
from game_chat_translator.runtime.queues import GenerationalQueue, LatestValueQueue, OfferResult
from game_chat_translator.vision.base import (
    CancellationToken,
    OcrInput,
    OcrOutcome,
    ProviderHealth,
)
from game_chat_translator.vision.calibration_preview import Preprocessor
from game_chat_translator.vision.color_sampling import attach_source_colors
from game_chat_translator.vision.line_grouping import group_fragments
from game_chat_translator.vision.line_tracker import LineTracker
from game_chat_translator.vision.ocr_service import EventCancellationToken
from game_chat_translator.vision.preprocess import PreprocessConfig


class RecognitionService(Protocol):
    def recognize(
        self,
        request: OcrInput,
        *,
        generation: Callable[[], int],
        cancellation: CancellationToken | None = None,
    ) -> OcrOutcome: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class FrameWork:
    frame: CapturedFrame
    preprocess: PreprocessConfig
    generation: int


@dataclass(frozen=True, slots=True)
class TrackedLines:
    lines: tuple[ChatLine, ...]
    generation: int


@dataclass(frozen=True, slots=True)
class PipelineUpdate:
    health: ProviderHealth
    generation: int
    emitted_count: int
    error_code: str | None = None


class OcrPipeline:
    """Worker-side capture→preprocess→OCR→group→track orchestration."""

    def __init__(
        self,
        preprocessor: Preprocessor,
        service: RecognitionService,
        tracker: LineTracker,
        *,
        initial_generation: int,
        publish_status: Callable[[PipelineUpdate], None],
    ) -> None:
        self._preprocessor = preprocessor
        self._service = service
        self._tracker = tracker
        self._frames: LatestValueQueue[FrameWork] = LatestValueQueue()
        self._results = GenerationalQueue[TrackedLines](
            2, lambda item: item.generation, initial_generation=initial_generation
        )
        self._generation = initial_generation
        self._publish_status = publish_status
        self._cancellation = EventCancellationToken()
        self._pending: TrackedLines | None = None
        self._lock = Lock()

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    def submit(self, work: FrameWork) -> OfferResult:
        with self._lock:
            if work.generation != self._generation:
                return OfferResult.REJECTED_OBSOLETE
            return self._frames.offer(work)

    def advance_generation(self, generation: int) -> None:
        with self._lock:
            if generation < self._generation:
                raise ValueError("pipeline generation cannot move backwards")
            if generation == self._generation:
                return
            self._generation = generation
            self._cancellation.cancel()
            self._cancellation = EventCancellationToken()
            self._frames.clear()
            self._results.advance_generation(generation)
            self._pending = None
            self._tracker.reset(generation=generation)

    def process_next(self) -> PipelineUpdate | None:
        pending_update = self._flush_pending()
        if pending_update is not None:
            return pending_update
        work = self._frames.take()
        if work is None:
            return None
        if work.generation != self.generation:
            return self._publish(
                PipelineUpdate(
                    ProviderHealth.DEGRADED,
                    work.generation,
                    0,
                    "OCR_OBSOLETE_GENERATION",
                )
            )
        try:
            raw = RawFrame(
                work.frame.width,
                work.frame.height,
                work.frame.pixel_format,
                work.frame.pixels,
            )
            processed = self._preprocessor.process(raw, work.preprocess)
            request = OcrInput(
                processed.pixels,
                processed.width,
                processed.height,
                processed.channels,
                work.generation,
            )
        except (RuntimeError, TypeError, ValueError):
            return self._publish(
                PipelineUpdate(ProviderHealth.DEGRADED, work.generation, 0, "OCR_PREPROCESS_FAILED")
            )
        outcome = self._service.recognize(
            request,
            generation=lambda: self.generation,
            cancellation=self._cancellation,
        )
        if outcome.error_code is not None:
            return self._publish(
                PipelineUpdate(outcome.health, work.generation, 0, outcome.error_code)
            )
        colored_fragments = attach_source_colors(
            outcome.fragments,
            raw,
            preprocess_scale=work.preprocess.scale,
            candidate_colors=work.preprocess.text_colors,
            tolerance=work.preprocess.color_tolerance,
        )
        lines = group_fragments(colored_fragments)
        with self._lock:
            if work.generation != self._generation:
                update = PipelineUpdate(
                    ProviderHealth.DEGRADED,
                    work.generation,
                    0,
                    "OCR_OBSOLETE_GENERATION",
                )
            else:
                emitted = self._tracker.accept(lines, generation=work.generation)
                if not emitted:
                    update = PipelineUpdate(outcome.health, work.generation, 0)
                else:
                    tracked = TrackedLines(emitted, work.generation)
                    offered = self._results.offer(tracked)
                    if offered is OfferResult.ACCEPTED:
                        update = PipelineUpdate(outcome.health, work.generation, len(emitted))
                    else:
                        self._pending = tracked
                        update = PipelineUpdate(
                            ProviderHealth.DEGRADED,
                            work.generation,
                            0,
                            "OCR_RESULTS_BACKPRESSURE",
                        )
        return self._publish(update)

    def take_result(self) -> TrackedLines | None:
        return self._results.take()

    def close(self) -> None:
        self._cancellation.cancel()
        self._frames.clear()
        self._results.clear()
        self._pending = None
        self._service.close()

    def _publish(self, update: PipelineUpdate) -> PipelineUpdate:
        self._publish_status(update)
        return update

    def _flush_pending(self) -> PipelineUpdate | None:
        with self._lock:
            pending = self._pending
            if pending is None:
                return None
            if pending.generation != self._generation:
                self._pending = None
                update = PipelineUpdate(
                    ProviderHealth.DEGRADED,
                    pending.generation,
                    0,
                    "OCR_OBSOLETE_GENERATION",
                )
            elif self._results.offer(pending) is not OfferResult.ACCEPTED:
                update = PipelineUpdate(
                    ProviderHealth.DEGRADED,
                    pending.generation,
                    0,
                    "OCR_RESULTS_BACKPRESSURE",
                )
            else:
                self._pending = None
                update = PipelineUpdate(
                    ProviderHealth.READY, pending.generation, len(pending.lines)
                )
        return self._publish(update)
