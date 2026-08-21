from __future__ import annotations

from datetime import UTC, datetime
from threading import Event, Thread
from uuid import UUID, uuid4

from game_chat_translator.models import MessageClass
from game_chat_translator.runtime.queues import OfferResult
from game_chat_translator.translation import (
    ContextEntry,
    ContextManager,
    TranslationJob,
    TranslationPipeline,
    TranslationRequestBuilder,
    TranslationRouter,
)
from game_chat_translator.translation.base import (
    CancellationToken,
    TranslationCancelled,
    TranslationRequest,
)


class _Provider:
    provider_id = "fake"
    model_id = "fake-v1"

    def __init__(self) -> None:
        self.on_translate = lambda: None

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
        self.on_translate()
        return f"en:{request.source_text}"

    def close(self) -> None:
        pass


def _job(message_id: UUID | None = None, *, generation: int = 1) -> TranslationJob:
    request = TranslationRequestBuilder().build(
        "привет",
        source_language="ru",
        context_generation=generation,
        glossary_generation=generation,
        model_generation=generation,
    )
    return TranslationJob(message_id or uuid4(), request, generation, generation, generation)


def test_result_backpressure_preserves_every_accepted_message_in_order() -> None:
    provider = _Provider()
    pipeline = TranslationPipeline(
        TranslationRouter(provider, None),
        request_capacity=2,
        result_capacity=1,
        initial_generations=(1, 1, 1, 1, 1, 1),
    )
    first, second = uuid4(), uuid4()
    assert pipeline.offer(_job(first)) is OfferResult.ACCEPTED
    assert pipeline.offer(_job(second)) is OfferResult.ACCEPTED
    assert pipeline.process_next() is OfferResult.ACCEPTED
    assert pipeline.process_next() is OfferResult.REJECTED_FULL
    assert pipeline.take().message_id == first  # type: ignore[union-attr]
    assert pipeline.process_next() is OfferResult.ACCEPTED
    assert pipeline.take().message_id == second  # type: ignore[union-attr]
    assert pipeline.take() is None


def test_generation_change_during_inference_never_publishes_obsolete_result() -> None:
    provider = _Provider()
    pipeline = TranslationPipeline(
        TranslationRouter(provider, None), initial_generations=(1, 1, 1, 1, 1, 1)
    )
    provider.on_translate = lambda: pipeline.advance_generations(
        profile=2, layout=2, context=2, glossary=2, model=2, config=2
    )
    assert pipeline.offer(_job()) is OfferResult.ACCEPTED
    assert pipeline.process_next() is OfferResult.REJECTED_OBSOLETE
    assert pipeline.take() is None


def test_context_is_bounded_expires_with_fake_time_and_clears_immediately() -> None:
    now = 0.0
    context = ContextManager(maximum_messages=3, maximum_age_seconds=10, monotonic=lambda: now)
    for index in range(4):
        now = float(index)
        context.add(
            ContextEntry(
                speaker=f"p{index}",
                channel="global",
                created_at=datetime(2026, 8, 20, tzinfo=UTC),
                monotonic_seconds=now,
                language="ru",
                direction=MessageClass.PLAYER_INBOUND,
                source_text=f"line {index}",
            )
        )
    assert [item.source_text for item in context.snapshot()] == ["line 1", "line 2", "line 3"]
    generation = context.generation
    now = 20
    assert context.snapshot() == ()
    assert context.generation == generation + 1
    context.clear()
    assert context.snapshot() == ()


def test_close_during_inference_never_publishes_after_shutdown() -> None:
    provider = _Provider()
    started, release = Event(), Event()

    def barrier() -> None:
        started.set()
        release.wait(timeout=2)

    provider.on_translate = barrier
    pipeline = TranslationPipeline(
        TranslationRouter(provider, None), initial_generations=(1, 1, 1, 1, 1, 1)
    )
    assert pipeline.offer(_job()) is OfferResult.ACCEPTED
    outcomes: list[OfferResult | None] = []
    worker = Thread(target=lambda: outcomes.append(pipeline.process_next()))
    worker.start()
    assert started.wait(timeout=2)
    pipeline.close()
    release.set()
    worker.join(timeout=2)
    assert outcomes == [OfferResult.REJECTED_OBSOLETE]
    assert pipeline.take() is None


class _CancelledToken:
    cancelled = True


def test_cancelled_accepted_job_is_not_published() -> None:
    pipeline = TranslationPipeline(
        TranslationRouter(_Provider(), None), initial_generations=(1, 1, 1, 1, 1, 1)
    )
    assert pipeline.offer(_job()) is OfferResult.ACCEPTED
    assert pipeline.process_next(_CancelledToken()) is OfferResult.REJECTED_CANCELLED
    assert pipeline.take() is None


class _GenerationAwareProvider(_Provider):
    def __init__(self, started: Event) -> None:
        super().__init__()
        self.started = started
        self.calls = 0

    def translate(
        self,
        request: TranslationRequest,
        *,
        timeout_seconds: float,
        cancellation: CancellationToken | None = None,
    ) -> str:
        del timeout_seconds
        self.calls += 1
        if self.calls == 1:
            self.started.set()
            assert cancellation is not None
            while not cancellation.cancelled:
                self.started.wait(timeout=0.01)
            raise TranslationCancelled("obsolete generation")
        return f"en:{request.source_text}"


def test_generation_advance_cancels_old_work_before_new_job() -> None:
    started = Event()
    provider = _GenerationAwareProvider(started)
    pipeline = TranslationPipeline(
        TranslationRouter(provider, None), initial_generations=(1, 1, 1, 1, 1, 1)
    )
    assert pipeline.offer(_job()) is OfferResult.ACCEPTED
    outcomes: list[OfferResult | None] = []
    worker = Thread(target=lambda: outcomes.append(pipeline.process_next()))
    worker.start()
    assert started.wait(timeout=2)
    pipeline.advance_generations(profile=2, layout=2, context=2, glossary=2, model=2, config=2)
    worker.join(timeout=2)
    assert outcomes == [OfferResult.REJECTED_CANCELLED]
    assert pipeline.offer(_job(generation=2)) is OfferResult.ACCEPTED
    assert pipeline.process_next() is OfferResult.ACCEPTED
    assert pipeline.take() is not None
