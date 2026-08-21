from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from contextlib import suppress
from threading import Event, Lock, Thread

from game_chat_translator.speech.base import SpeechJob, SpeechProvider, SpeechSettings
from game_chat_translator.speech.queue import SpeechOfferResult, SpeechQueue


class SpeechWorker:
    def __init__(
        self,
        provider_factory: Callable[[], SpeechProvider],
        *,
        capacity: int = 64,
        monotonic: Callable[[], float] = time.monotonic,
        settings: SpeechSettings | None = None,
        on_failure: Callable[[str], None] | None = None,
    ) -> None:
        self._factory = provider_factory
        self._queue = SpeechQueue(capacity)
        self._monotonic = monotonic
        self._settings = settings or SpeechSettings()
        self._on_failure = on_failure or (lambda _code: None)
        self._lock = Lock()
        self._stop = Event()
        self._finished = Event()
        self._interrupt = Event()
        self._muted = False
        self._paused = False
        self._thread: Thread | None = None
        self._voice_requests: deque[tuple[Event, list[tuple[str, str]]]] = deque()

    def start(self) -> None:
        with self._lock:
            if self._thread is not None:
                return
            self._thread = Thread(target=self._run, name="gct-speech", daemon=True)
            self._thread.start()

    def offer(self, item: SpeechJob) -> SpeechOfferResult:
        with self._lock:
            if self._muted:
                return SpeechOfferResult.REJECTED_MUTED
        return self._queue.offer(item, now=self._monotonic())

    def submit(self, item: SpeechJob, *, timeout: float | None = None) -> SpeechOfferResult:
        with self._lock:
            if self._muted:
                return SpeechOfferResult.REJECTED_MUTED
        return self._queue.put(item, now=self._monotonic(), timeout=timeout)

    def set_muted(self, muted: bool) -> None:
        with self._lock:
            self._muted = muted
            if muted:
                self._interrupt.set()
                self._queue.purge()
        self._queue.wake()

    def set_paused(self, paused: bool) -> None:
        with self._lock:
            self._paused = paused
            if paused:
                self._interrupt.set()
        self._queue.wake()

    def update_settings(self, settings: SpeechSettings) -> None:
        with self._lock:
            self._settings = settings

    def voices(self, *, timeout: float = 5.0) -> tuple[tuple[str, str], ...]:
        if timeout <= 0:
            raise ValueError("voice query timeout must be positive")
        self.start()
        completed = Event()
        result: list[tuple[str, str]] = []
        with self._lock:
            if self._stop.is_set() or self._finished.is_set():
                return ()
            self._voice_requests.append((completed, result))
        self._queue.wake()
        if not completed.wait(timeout):
            return ()
        return tuple(result)

    def close(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self._interrupt.set()
        self._queue.close()
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
            if thread.is_alive():
                raise RuntimeError("speech worker did not stop")

    def _run(self) -> None:
        provider: SpeechProvider | None = None
        pending: SpeechJob | None = None
        try:
            provider = self._factory()
            while not self._stop.is_set():
                request: tuple[Event, list[tuple[str, str]]] | None = None
                with self._lock:
                    paused = self._paused
                    muted = self._muted
                    settings = self._settings
                    if self._voice_requests:
                        request = self._voice_requests.popleft()
                if request is not None:
                    completed, result = request
                    try:
                        result.extend(provider.voices())
                    except Exception:
                        self._on_failure("SPEECH_VOICE_ENUMERATION_FAILED")
                    finally:
                        completed.set()
                    continue
                if paused or muted:
                    if muted:
                        pending = None
                    self._stop.wait(0.02)
                    continue
                if pending is None:
                    pending = self._queue.take(now=self._monotonic(), timeout=0.05)
                if pending is None:
                    continue
                # Pause/mute may race with a blocking take; recheck before provider entry.
                with self._lock:
                    if self._paused or self._muted:
                        continue
                    settings = self._settings
                self._interrupt.clear()
                try:
                    provider.speak(pending.text, settings, cancellation=_Cancellation(self))
                except Exception:
                    self._on_failure("SPEECH_PROVIDER_FAILED")
                    with suppress(Exception):
                        provider.cancel()
                finally:
                    pending = None
        except Exception:
            self._on_failure("SPEECH_PROVIDER_UNAVAILABLE")
        finally:
            with self._lock:
                pending_requests = tuple(self._voice_requests)
                self._voice_requests.clear()
                self._finished.set()
            for completed, _result in pending_requests:
                completed.set()
            if provider is not None:
                with suppress(Exception):
                    provider.cancel()
                with suppress(Exception):
                    provider.close()


class _Cancellation:
    def __init__(self, worker: SpeechWorker) -> None:
        self._worker = worker

    @property
    def cancelled(self) -> bool:
        return self._worker._stop.is_set() or self._worker._interrupt.is_set()
