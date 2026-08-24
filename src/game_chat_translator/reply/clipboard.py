from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Event, Lock


@dataclass(slots=True)
class _CopyRequest:
    text: str
    completed: Event = field(default_factory=Event)
    cancelled: Event = field(default_factory=Event)
    result: bool = False


class ClipboardDispatchBridge:
    """Bounded worker-to-UI clipboard handoff with no delayed writes after timeout."""

    def __init__(self, *, capacity: int = 8) -> None:
        if not 1 <= capacity <= 64:
            raise ValueError("clipboard dispatch capacity is invalid")
        self._capacity = capacity
        self._requests: deque[_CopyRequest] = deque()
        self._lock = Lock()
        self._closed = False

    def request_copy(self, text: str, *, timeout: float = 5.0) -> bool:
        if not text or len(text) > 8_192 or timeout <= 0:
            return False
        request = _CopyRequest(text)
        with self._lock:
            if self._closed or len(self._requests) >= self._capacity:
                return False
            self._requests.append(request)
        if not request.completed.wait(timeout):
            request.cancelled.set()
            return False
        return request.result

    def process(self, copy: Callable[[str], bool], *, maximum: int = 8) -> int:
        if maximum <= 0:
            raise ValueError("clipboard processing maximum must be positive")
        with self._lock:
            requests = tuple(
                self._requests.popleft() for _ in range(min(maximum, len(self._requests)))
            )
        processed = 0
        for request in requests:
            if not request.cancelled.is_set():
                try:
                    request.result = bool(copy(request.text))
                except Exception:
                    request.result = False
                processed += 1
            request.completed.set()
        return processed

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            requests = tuple(self._requests)
            self._requests.clear()
        for request in requests:
            request.cancelled.set()
            request.completed.set()
