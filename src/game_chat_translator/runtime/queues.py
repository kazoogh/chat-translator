from __future__ import annotations

from collections import deque
from collections.abc import Callable
from enum import StrEnum
from threading import Lock


class OfferResult(StrEnum):
    ACCEPTED = "accepted"
    PARTIALLY_ACCEPTED = "partially_accepted"
    REPLACED_STALE = "replaced_stale"
    REJECTED_FULL = "rejected_full"
    REJECTED_OBSOLETE = "rejected_obsolete"
    REJECTED_CANCELLED = "rejected_cancelled"


class LatestValueQueue[T]:
    """Capacity-one queue where a new frame explicitly replaces the stale frame."""

    def __init__(self) -> None:
        self._item: T | None = None
        self._lock = Lock()

    def offer(self, item: T) -> OfferResult:
        with self._lock:
            replaced = self._item is not None
            self._item = item
        return OfferResult.REPLACED_STALE if replaced else OfferResult.ACCEPTED

    def take(self) -> T | None:
        with self._lock:
            item, self._item = self._item, None
            return item

    def clear(self) -> None:
        with self._lock:
            self._item = None

    def __len__(self) -> int:
        with self._lock:
            return int(self._item is not None)


class GenerationalQueue[T]:
    """Bounded queue that rejects stale work and purges stale generations."""

    def __init__(
        self, capacity: int, generation_of: Callable[[T], int], *, initial_generation: int
    ) -> None:
        if capacity <= 0:
            raise ValueError("queue capacity must be positive")
        self._capacity = capacity
        self._generation_of = generation_of
        self._generation = initial_generation
        self._items: deque[T] = deque()
        self._lock = Lock()

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    def advance_generation(self, generation: int) -> None:
        with self._lock:
            if generation < self._generation:
                raise ValueError("queue generation cannot move backwards")
            self._generation = generation
            self._purge_locked()

    def offer(self, item: T) -> OfferResult:
        with self._lock:
            if self._generation_of(item) != self._generation:
                return OfferResult.REJECTED_OBSOLETE
            if len(self._items) >= self._capacity:
                return OfferResult.REJECTED_FULL
            self._items.append(item)
            return OfferResult.ACCEPTED

    def take(self) -> T | None:
        with self._lock:
            self._purge_locked()
            return self._items.popleft() if self._items else None

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def _purge_locked(self) -> None:
        self._items = deque(
            item for item in self._items if self._generation_of(item) == self._generation
        )
