from __future__ import annotations

from datetime import UTC, datetime
from threading import Event, Thread
from uuid import uuid4

import pytest

from game_chat_translator.events import AppError, ErrorSeverity
from game_chat_translator.models import MessageClass
from game_chat_translator.ui.event_queue import (
    PresentedMessage,
    UiEventKind,
    UiEventQueue,
    UiQueueClosed,
    UiStatus,
)


def _message(text: str) -> PresentedMessage:
    return PresentedMessage(
        uuid4(),
        datetime.now(UTC),
        MessageClass.PLAYER_INBOUND,
        "player",
        text,
        f"translated {text}",
    )


def test_lossless_events_backpressure_without_eviction_and_preserve_fifo() -> None:
    queue = UiEventQueue(capacity=2)
    first, second, third = _message("one"), _message("two"), _message("three")
    queue.publish_message(first)
    queue.publish_message(second)
    completed = Event()

    def publish_third() -> None:
        queue.publish_message(third)
        completed.set()

    producer = Thread(target=publish_third)
    producer.start()
    assert not completed.wait(0.05)
    assert queue.drain(maximum=1)[0].payload == first
    assert completed.wait(1)
    producer.join(1)
    assert [event.payload for event in queue.drain()] == [second, third]


def test_status_coalesces_but_messages_and_errors_do_not() -> None:
    queue = UiEventQueue(capacity=4)
    message = _message("one")
    error = AppError(
        code="TTS_FAILED",
        subsystem="speech",
        severity=ErrorSeverity.DEGRADED,
        user_message="Speech is temporarily unavailable.",
    )
    queue.publish_status("capture", "starting")
    queue.publish_message(message)
    queue.publish_status("capture", "monitoring")
    queue.publish_error(error)

    events = queue.drain()
    assert [event.kind for event in events] == [
        UiEventKind.MESSAGE,
        UiEventKind.ERROR,
        UiEventKind.STATUS,
    ]
    assert events[0].payload == message
    assert events[1].payload == error
    assert isinstance(events[2].payload, UiStatus)
    assert events[2].payload.value == "monitoring"


def test_close_unblocks_a_waiting_producer_and_rejects_new_work() -> None:
    queue = UiEventQueue(capacity=1)
    queue.publish_message(_message("one"))
    stopped = Event()

    def blocked_publish() -> None:
        with pytest.raises(UiQueueClosed):
            queue.publish_message(_message("two"))
        stopped.set()

    producer = Thread(target=blocked_publish)
    producer.start()
    queue.close()
    assert stopped.wait(1)
    producer.join(1)
    with pytest.raises(UiQueueClosed):
        queue.publish_status("capture", "stopped")
