from __future__ import annotations

from threading import Event, Thread
from uuid import uuid4

from game_chat_translator.speech import SpeechJob, SpeechOfferResult, SpeechQueue


def test_fifo_backpressure_and_exactly_once_ids_are_explicit() -> None:
    queue = SpeechQueue(2)
    first = SpeechJob(uuid4(), "first")
    second = SpeechJob(uuid4(), "second")
    third = SpeechJob(uuid4(), "third")
    assert queue.offer(first, now=0) is SpeechOfferResult.ACCEPTED
    assert queue.offer(second, now=0) is SpeechOfferResult.ACCEPTED
    assert queue.offer(third, now=0) is SpeechOfferResult.REJECTED_FULL
    assert queue.take(now=0) == first
    assert queue.take(now=0) == second
    assert queue.offer(first, now=0) is SpeechOfferResult.REJECTED_DUPLICATE
    assert queue.offer(third, now=0) is SpeechOfferResult.ACCEPTED


def test_only_expired_diagnostics_drop_and_normal_chat_is_never_evicted() -> None:
    queue = SpeechQueue(2)
    normal = SpeechJob(uuid4(), "normal", expires_monotonic=1)
    diagnostic = SpeechJob(uuid4(), "diagnostic", expires_monotonic=1, diagnostic=True)
    assert queue.offer(normal, now=0) is SpeechOfferResult.ACCEPTED
    assert queue.offer(diagnostic, now=0) is SpeechOfferResult.ACCEPTED
    replacement = SpeechJob(uuid4(), "replacement")
    assert queue.offer(replacement, now=2) is SpeechOfferResult.ACCEPTED
    assert queue.take(now=2) == normal
    assert queue.take(now=2) == replacement
    expired = SpeechJob(uuid4(), "old diagnostic", expires_monotonic=1, diagnostic=True)
    assert queue.offer(expired, now=2) is SpeechOfferResult.DROPPED_EXPIRED_DIAGNOSTIC


def test_blocking_put_applies_backpressure_until_fifo_capacity_is_available() -> None:
    queue = SpeechQueue(1)
    first = SpeechJob(uuid4(), "first")
    second = SpeechJob(uuid4(), "second")
    assert queue.put(first, now=0) is SpeechOfferResult.ACCEPTED
    completed = Event()

    def put_second() -> None:
        assert queue.put(second, now=0) is SpeechOfferResult.ACCEPTED
        completed.set()

    producer = Thread(target=put_second)
    producer.start()
    assert not completed.wait(0.05)
    assert queue.take(now=0) == first
    assert completed.wait(1)
    producer.join(1)
    assert queue.take(now=0) == second
