from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from threading import Condition
from time import monotonic
from uuid import UUID

from game_chat_translator.events import AppError
from game_chat_translator.models import MessageClass


class UiEventKind(StrEnum):
    MESSAGE = "message"
    ERROR = "error"
    STATUS = "status"


@dataclass(frozen=True, slots=True)
class PresentedMessage:
    message_id: UUID
    created_at: datetime
    classification: MessageClass
    speaker: str | None
    source_text: str
    translated_text: str
    warning_codes: tuple[str, ...] = ()
    announce: bool = True


@dataclass(frozen=True, slots=True)
class UiStatus:
    key: str
    value: str


@dataclass(frozen=True, slots=True)
class UiEvent:
    kind: UiEventKind
    payload: PresentedMessage | AppError | UiStatus


class UiQueueClosed(RuntimeError):
    pass


class UiBackpressureTimeout(RuntimeError):
    pass


class UiEventQueue:
    """Lossless message/error FIFO plus independently coalesced status updates."""

    def __init__(self, *, capacity: int = 256) -> None:
        if capacity <= 0:
            raise ValueError("UI event capacity must be positive")
        self._capacity = capacity
        self._lossless: deque[UiEvent] = deque()
        self._statuses: dict[str, UiEvent] = {}
        self._condition = Condition()
        self._closed = False

    def publish_message(
        self,
        message: PresentedMessage,
        *,
        cancelled: Callable[[], bool] = lambda: False,
        timeout_seconds: float | None = None,
    ) -> None:
        self._publish_lossless(
            UiEvent(UiEventKind.MESSAGE, message),
            cancelled=cancelled,
            timeout_seconds=timeout_seconds,
        )

    def publish_error(
        self,
        error: AppError,
        *,
        cancelled: Callable[[], bool] = lambda: False,
        timeout_seconds: float | None = None,
    ) -> None:
        self._publish_lossless(
            UiEvent(UiEventKind.ERROR, error),
            cancelled=cancelled,
            timeout_seconds=timeout_seconds,
        )

    def publish_status(self, key: str, value: str) -> None:
        if not key:
            raise ValueError("status key must not be empty")
        with self._condition:
            if self._closed:
                raise UiQueueClosed("UI event queue is closed")
            self._statuses[key] = UiEvent(UiEventKind.STATUS, UiStatus(key, value))

    def drain(self, *, maximum: int = 64) -> tuple[UiEvent, ...]:
        if maximum <= 0:
            raise ValueError("drain maximum must be positive")
        with self._condition:
            events: list[UiEvent] = []
            while self._lossless and len(events) < maximum:
                events.append(self._lossless.popleft())
            if len(events) < maximum and self._statuses:
                remaining = maximum - len(events)
                keys = tuple(self._statuses)[:remaining]
                events.extend(self._statuses.pop(key) for key in keys)
            if events:
                self._condition.notify_all()
            return tuple(events)

    def clear_messages(self) -> int:
        with self._condition:
            before = len(self._lossless)
            self._lossless = deque(
                event for event in self._lossless if event.kind is not UiEventKind.MESSAGE
            )
            removed = before - len(self._lossless)
            if removed:
                self._condition.notify_all()
            return removed

    def close(self) -> None:
        with self._condition:
            if self._closed:
                return
            self._closed = True
            self._lossless.clear()
            self._statuses.clear()
            self._condition.notify_all()

    def __len__(self) -> int:
        with self._condition:
            return len(self._lossless) + len(self._statuses)

    def _publish_lossless(
        self,
        event: UiEvent,
        *,
        cancelled: Callable[[], bool],
        timeout_seconds: float | None,
    ) -> None:
        if timeout_seconds is not None and timeout_seconds < 0:
            raise ValueError("timeout must not be negative")
        deadline = None if timeout_seconds is None else monotonic() + timeout_seconds
        with self._condition:
            while len(self._lossless) >= self._capacity:
                if self._closed:
                    raise UiQueueClosed("UI event queue is closed")
                if cancelled():
                    raise UiQueueClosed("UI event publication was cancelled")
                remaining = None if deadline is None else deadline - monotonic()
                if remaining is not None and remaining <= 0:
                    raise UiBackpressureTimeout("UI event queue remained full")
                self._condition.wait(remaining)
            if self._closed:
                raise UiQueueClosed("UI event queue is closed")
            if cancelled():
                raise UiQueueClosed("UI event publication was cancelled")
            self._lossless.append(event)
            self._condition.notify_all()
