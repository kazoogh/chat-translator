from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from game_chat_translator.models import MessageClass
from game_chat_translator.runtime.queues import GenerationalQueue, LatestValueQueue
from game_chat_translator.speech.base import SpeechJob
from game_chat_translator.speech.queue import SpeechOfferResult, SpeechQueue
from game_chat_translator.ui.event_queue import PresentedMessage, UiEventKind, UiEventQueue


def _identity(index: int) -> UUID:
    return UUID(int=index + 1)


def test_accelerated_high_volume_queues_remain_bounded_and_ordered() -> None:
    frames = LatestValueQueue[int]()
    ocr = GenerationalQueue[tuple[int, int]](
        2, generation_of=lambda item: item[0], initial_generation=0
    )
    speech = SpeechQueue(8)
    ui = UiEventQueue(capacity=16)
    displayed: list[UUID] = []
    spoken: list[UUID] = []

    for index in range(50_000):
        frames.offer(index)
        assert len(frames) <= 1

        generation = index // 1_000
        if generation != ocr.generation:
            ocr.advance_generation(generation)
        ocr.offer((generation, index))
        assert len(ocr) <= 2
        if index % 2 == 0:
            ocr.take()

        identifier = _identity(index)
        assert (
            speech.offer(SpeechJob(identifier, "bounded chat"), now=float(index))
            is SpeechOfferResult.ACCEPTED
        )
        item = speech.take(now=float(index), timeout=0)
        assert item is not None
        spoken.append(item.message_id)

        ui.publish_status(f"worker-{index % 8}", str(index))
        if index % 100 == 0:
            ui.publish_message(
                PresentedMessage(
                    identifier,
                    datetime(2026, 1, 1, tzinfo=UTC),
                    MessageClass.PLAYER_INBOUND,
                    "speaker",
                    "source",
                    "translation",
                )
            )
        if index % 16 == 15:
            displayed.extend(
                event.payload.message_id
                for event in ui.drain(maximum=32)
                if event.kind is UiEventKind.MESSAGE and isinstance(event.payload, PresentedMessage)
            )
        assert len(ui) <= 24

    displayed.extend(
        event.payload.message_id
        for event in ui.drain(maximum=64)
        if event.kind is UiEventKind.MESSAGE and isinstance(event.payload, PresentedMessage)
    )
    assert spoken == [_identity(index) for index in range(50_000)]
    assert displayed == [_identity(index) for index in range(0, 50_000, 100)]
