from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from threading import Event, Lock
from uuid import UUID

from game_chat_translator.runtime.queues import OfferResult
from game_chat_translator.translation.base import (
    CancellationToken,
    TranslationCancelled,
    TranslationOutcome,
    TranslationRequest,
)
from game_chat_translator.translation.router import TranslationRouter


@dataclass(frozen=True, slots=True)
class TranslationJob:
    message_id: UUID
    request: TranslationRequest
    profile_generation: int
    layout_generation: int
    config_generation: int


@dataclass(frozen=True, slots=True)
class PublishedTranslation:
    message_id: UUID
    outcome: TranslationOutcome
    profile_generation: int
    layout_generation: int
    context_generation: int
    glossary_generation: int
    model_generation: int
    config_generation: int


class TranslationPipeline:
    """Single-owner bounded FIFO with commit-time generation validation."""

    def __init__(
        self,
        router: TranslationRouter,
        *,
        request_capacity: int = 64,
        result_capacity: int = 64,
        initial_generations: tuple[int, int, int, int, int, int] = (0, 0, 0, 0, 0, 0),
    ) -> None:
        if request_capacity <= 0 or result_capacity <= 0:
            raise ValueError("translation queue capacities must be positive")
        self._router = router
        self._request_capacity = request_capacity
        self._result_capacity = result_capacity
        self._generations = initial_generations
        self._requests: deque[TranslationJob] = deque()
        self._results: deque[PublishedTranslation] = deque()
        self._pending: PublishedTranslation | None = None
        self._lock = Lock()
        self._closed = False
        self._generation_cancel = Event()

    @property
    def generations(self) -> tuple[int, int, int, int, int, int]:
        with self._lock:
            return self._generations

    def offer(self, job: TranslationJob) -> OfferResult:
        with self._lock:
            if self._closed or self._job_generations(job) != self._generations:
                return OfferResult.REJECTED_OBSOLETE
            if len(self._requests) >= self._request_capacity:
                return OfferResult.REJECTED_FULL
            self._requests.append(job)
            return OfferResult.ACCEPTED

    def process_next(self, cancellation: CancellationToken | None = None) -> OfferResult | None:
        with self._lock:
            if self._pending is not None:
                if len(self._results) >= self._result_capacity:
                    return OfferResult.REJECTED_FULL
                self._results.append(self._pending)
                self._pending = None
                return OfferResult.ACCEPTED
            if not self._requests or self._closed:
                return None
            job = self._requests.popleft()
            generation_cancel = self._generation_cancel
        combined = _CombinedCancellation(generation_cancel, cancellation)
        try:
            outcome = self._router.translate(job.request, combined)
        except TranslationCancelled:
            return OfferResult.REJECTED_CANCELLED
        published = PublishedTranslation(
            message_id=job.message_id,
            outcome=outcome,
            profile_generation=job.profile_generation,
            layout_generation=job.layout_generation,
            context_generation=job.request.context_generation,
            glossary_generation=job.request.glossary_generation,
            model_generation=job.request.model_generation,
            config_generation=job.config_generation,
        )
        with self._lock:
            if self._closed or self._published_generations(published) != self._generations:
                return OfferResult.REJECTED_OBSOLETE
            if len(self._results) >= self._result_capacity:
                self._pending = published
                return OfferResult.REJECTED_FULL
            self._results.append(published)
            return OfferResult.ACCEPTED

    def take(self) -> PublishedTranslation | None:
        with self._lock:
            return self._results.popleft() if self._results else None

    def advance_generations(
        self,
        *,
        profile: int,
        layout: int,
        context: int,
        glossary: int,
        model: int,
        config: int,
    ) -> None:
        updated = (profile, layout, context, glossary, model, config)
        with self._lock:
            if any(new < old for new, old in zip(updated, self._generations, strict=True)):
                raise ValueError("translation generations cannot move backwards")
            if updated != self._generations:
                self._generation_cancel.set()
                self._generation_cancel = Event()
            self._generations = updated
            self._requests = deque(
                item for item in self._requests if self._job_generations(item) == updated
            )
            self._results = deque(
                item for item in self._results if self._published_generations(item) == updated
            )
            if self._pending is not None and self._published_generations(self._pending) != updated:
                self._pending = None

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._generation_cancel.set()
            self._requests.clear()
            self._results.clear()
            self._pending = None
        self._router.close()

    def clear_history(self) -> None:
        """Cancel queued context work and remove every cached translation outcome."""
        with self._lock:
            if self._closed:
                return
            self._generation_cancel.set()
            self._generation_cancel = Event()
            profile, layout, context, glossary, model, config = self._generations
            self._generations = (profile, layout, context + 1, glossary, model, config)
            self._requests.clear()
            self._results.clear()
            self._pending = None
        self._router.clear_cache()

    @staticmethod
    def _job_generations(job: TranslationJob) -> tuple[int, int, int, int, int, int]:
        return (
            job.profile_generation,
            job.layout_generation,
            job.request.context_generation,
            job.request.glossary_generation,
            job.request.model_generation,
            job.config_generation,
        )

    @staticmethod
    def _published_generations(
        item: PublishedTranslation,
    ) -> tuple[int, int, int, int, int, int]:
        return (
            item.profile_generation,
            item.layout_generation,
            item.context_generation,
            item.glossary_generation,
            item.model_generation,
            item.config_generation,
        )


class _CombinedCancellation:
    def __init__(self, internal: Event, external: CancellationToken | None) -> None:
        self._internal = internal
        self._external = external

    @property
    def cancelled(self) -> bool:
        return self._internal.is_set() or (self._external is not None and self._external.cancelled)
