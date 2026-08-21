from __future__ import annotations

from collections import deque
from enum import StrEnum
from threading import Condition
from time import monotonic

from game_chat_translator.speech.base import SpeechJob


class SpeechOfferResult(StrEnum):
    ACCEPTED = "accepted"
    REJECTED_FULL = "rejected_full"
    REJECTED_DUPLICATE = "rejected_duplicate"
    REJECTED_CLOSED = "rejected_closed"
    REJECTED_MUTED = "rejected_muted"
    DROPPED_EXPIRED_DIAGNOSTIC = "dropped_expired_diagnostic"


class SpeechQueue:
    """Bounded FIFO; normal chat is never evicted and duplicate IDs are explicit."""

    def __init__(self, capacity: int) -> None:
        if capacity <= 0:
            raise ValueError("speech queue capacity must be positive")
        self._capacity = capacity
        self._items: deque[SpeechJob] = deque()
        self._seen: set[object] = set()
        self._seen_order: deque[object] = deque()
        self._seen_capacity = max(256, capacity * 4)
        self._condition = Condition()
        self._closed = False

    def offer(self, item: SpeechJob, *, now: float) -> SpeechOfferResult:
        with self._condition:
            if self._closed:
                return SpeechOfferResult.REJECTED_CLOSED
            if item.message_id in self._seen:
                return SpeechOfferResult.REJECTED_DUPLICATE
            expired = item.expires_monotonic is not None and item.expires_monotonic <= now
            if item.diagnostic and expired:
                self._remember_locked(item.message_id)
                return SpeechOfferResult.DROPPED_EXPIRED_DIAGNOSTIC
            self._drop_expired_diagnostics_locked(now)
            if len(self._items) >= self._capacity:
                return SpeechOfferResult.REJECTED_FULL
            self._items.append(item)
            self._remember_locked(item.message_id)
            self._condition.notify()
            return SpeechOfferResult.ACCEPTED

    def put(
        self,
        item: SpeechJob,
        *,
        now: float,
        timeout: float | None = None,
    ) -> SpeechOfferResult:
        """Wait for capacity so accepted normal chat is never silently discarded."""
        if timeout is not None and timeout < 0:
            raise ValueError("speech queue timeout cannot be negative")
        deadline = None if timeout is None else monotonic() + timeout
        with self._condition:
            if self._closed:
                return SpeechOfferResult.REJECTED_CLOSED
            if item.message_id in self._seen:
                return SpeechOfferResult.REJECTED_DUPLICATE
            expired = item.expires_monotonic is not None and item.expires_monotonic <= now
            if item.diagnostic and expired:
                self._remember_locked(item.message_id)
                return SpeechOfferResult.DROPPED_EXPIRED_DIAGNOSTIC
            self._drop_expired_diagnostics_locked(now)
            while len(self._items) >= self._capacity:
                remaining = None if deadline is None else deadline - monotonic()
                if remaining is not None and remaining <= 0:
                    return SpeechOfferResult.REJECTED_FULL
                self._condition.wait(remaining)
                if self._closed:
                    return SpeechOfferResult.REJECTED_CLOSED
                self._drop_expired_diagnostics_locked(now)
            self._items.append(item)
            self._remember_locked(item.message_id)
            self._condition.notify_all()
            return SpeechOfferResult.ACCEPTED

    def take(self, *, now: float, timeout: float | None = None) -> SpeechJob | None:
        with self._condition:
            self._drop_expired_diagnostics_locked(now)
            if not self._items and not self._closed:
                self._condition.wait(timeout)
                self._drop_expired_diagnostics_locked(now)
            item = self._items.popleft() if self._items else None
            if item is not None:
                self._condition.notify_all()
            return item

    def purge(self) -> int:
        with self._condition:
            count = len(self._items)
            self._items.clear()
            self._condition.notify_all()
            return count

    def wake(self) -> None:
        with self._condition:
            self._condition.notify_all()

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._items.clear()
            self._condition.notify_all()

    def _drop_expired_diagnostics_locked(self, now: float) -> None:
        self._items = deque(
            item
            for item in self._items
            if not (
                item.diagnostic
                and item.expires_monotonic is not None
                and item.expires_monotonic <= now
            )
        )

    def _remember_locked(self, message_id: object) -> None:
        self._seen.add(message_id)
        self._seen_order.append(message_id)
        while len(self._seen_order) > self._seen_capacity:
            self._seen.discard(self._seen_order.popleft())
