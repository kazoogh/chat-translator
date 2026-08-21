from __future__ import annotations

from dataclasses import dataclass
from threading import Barrier, Thread

from game_chat_translator.runtime.queues import GenerationalQueue, LatestValueQueue, OfferResult


@dataclass(frozen=True)
class Work:
    value: str
    generation: int


def test_latest_frame_queue_replaces_stale_frame_at_capacity_one() -> None:
    queue: LatestValueQueue[str] = LatestValueQueue()
    assert queue.offer("old") is OfferResult.ACCEPTED
    assert queue.offer("new") is OfferResult.REPLACED_STALE
    assert len(queue) == 1
    assert queue.take() == "new"
    assert queue.take() is None


def test_ocr_queue_has_capacity_two_and_rejects_obsolete_generations() -> None:
    queue = GenerationalQueue[Work](2, lambda item: item.generation, initial_generation=2)
    assert queue.offer(Work("old", 1)) is OfferResult.REJECTED_OBSOLETE
    assert queue.offer(Work("one", 2)) is OfferResult.ACCEPTED
    assert queue.offer(Work("two", 2)) is OfferResult.ACCEPTED
    assert queue.offer(Work("three", 2)) is OfferResult.REJECTED_FULL
    assert queue.take() == Work("one", 2)


def test_generation_change_purges_queued_ocr_results_before_publish() -> None:
    queue = GenerationalQueue[Work](2, lambda item: item.generation, initial_generation=4)
    queue.offer(Work("obsolete", 4))
    queue.advance_generation(5)
    assert queue.take() is None
    assert len(queue) == 0


def test_generation_advance_is_atomic_with_a_concurrent_producer() -> None:
    queue = GenerationalQueue[Work](2, lambda item: item.generation, initial_generation=1)
    barrier = Barrier(2)
    outcomes: list[OfferResult] = []

    def produce() -> None:
        barrier.wait()
        outcomes.append(queue.offer(Work("racing-old-work", 1)))

    producer = Thread(target=produce)
    producer.start()
    barrier.wait()
    queue.advance_generation(2)
    producer.join()
    queue.advance_generation(2)

    assert outcomes[0] in {OfferResult.ACCEPTED, OfferResult.REJECTED_OBSOLETE}
    assert queue.take() is None
