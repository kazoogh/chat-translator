from __future__ import annotations

from threading import Event, get_ident
from uuid import uuid4

from game_chat_translator.speech import SpeechJob, SpeechOfferResult, SpeechSettings, SpeechWorker


class _Provider:
    def __init__(self, *, fail_first: bool = False) -> None:
        self.created_thread = get_ident()
        self.calls: list[tuple[str, SpeechSettings]] = []
        self.closed_thread: int | None = None
        self.done = Event()
        self.fail_first = fail_first

    def voices(self) -> tuple[tuple[str, str], ...]:
        return (("voice-1", "Fixture Voice"),)

    def speak(self, text, settings, *, cancellation):  # type: ignore[no-untyped-def]
        self.calls.append((text, settings))
        if self.fail_first and len(self.calls) == 1:
            raise RuntimeError("fixture failure")
        self.done.set()

    def cancel(self) -> None:
        pass

    def close(self) -> None:
        self.closed_thread = get_ident()


def test_provider_is_owned_by_worker_and_failure_does_not_stop_fifo() -> None:
    providers: list[_Provider] = []
    failures: list[str] = []

    def factory() -> _Provider:
        provider = _Provider(fail_first=True)
        providers.append(provider)
        return provider

    worker = SpeechWorker(factory, on_failure=failures.append)
    worker.start()
    assert worker.offer(SpeechJob(uuid4(), "one")) is SpeechOfferResult.ACCEPTED
    assert worker.offer(SpeechJob(uuid4(), "two")) is SpeechOfferResult.ACCEPTED
    assert providers or _wait(lambda: bool(providers))
    provider = providers[0]
    assert provider.done.wait(2)
    worker.close()
    assert [text for text, _settings in provider.calls] == ["one", "two"]
    assert failures == ["SPEECH_PROVIDER_FAILED"]
    assert provider.created_thread != get_ident()
    assert provider.closed_thread == provider.created_thread


def test_voice_enumeration_runs_on_the_provider_owner_thread() -> None:
    providers: list[_Provider] = []

    def factory() -> _Provider:
        provider = _Provider()
        providers.append(provider)
        return provider

    worker = SpeechWorker(factory)
    assert worker.voices() == (("voice-1", "Fixture Voice"),)
    worker.close()
    provider = providers[0]
    assert provider.created_thread != get_ident()
    assert provider.closed_thread == provider.created_thread


def test_muted_rejects_new_speech_while_pause_preserves_fifo_until_resumed() -> None:
    provider = _Provider()
    worker = SpeechWorker(lambda: provider)
    worker.set_muted(True)
    worker.start()
    assert worker.offer(SpeechJob(uuid4(), "muted")) is SpeechOfferResult.REJECTED_MUTED
    assert not provider.done.wait(0.1)
    worker.set_muted(False)
    worker.set_paused(True)
    assert worker.offer(SpeechJob(uuid4(), "one")) is SpeechOfferResult.ACCEPTED
    assert worker.offer(SpeechJob(uuid4(), "two")) is SpeechOfferResult.ACCEPTED
    assert not provider.done.wait(0.1)
    worker.set_paused(False)
    assert provider.done.wait(2)
    assert _wait(lambda: len(provider.calls) == 2)
    worker.close()
    assert [text for text, _settings in provider.calls] == ["one", "two"]


def test_pause_replays_only_an_active_announcement_that_observed_cancellation() -> None:
    class BlockingProvider(_Provider):
        def __init__(self) -> None:
            super().__init__()
            self.started = Event()
            self.interrupted = Event()
            self.replayed = Event()

        def speak(self, text, settings, *, cancellation):  # type: ignore[no-untyped-def]
            self.calls.append((text, settings))
            if len(self.calls) == 1:
                self.started.set()
                assert _wait(lambda: cancellation.cancelled)
                self.interrupted.set()
                return
            self.replayed.set()

    provider = BlockingProvider()
    worker = SpeechWorker(lambda: provider)
    worker.start()
    assert worker.offer(SpeechJob(uuid4(), "interrupted")) is SpeechOfferResult.ACCEPTED
    assert provider.started.wait(2)

    worker.set_paused(True)
    assert provider.interrupted.wait(2)
    assert worker.wait_paused(2)
    worker.set_paused(False)

    assert provider.replayed.wait(2)
    worker.close()
    assert [text for text, _settings in provider.calls] == ["interrupted", "interrupted"]


def _wait(predicate, attempts: int = 100) -> bool:  # type: ignore[no-untyped-def]
    import time

    for _ in range(attempts):
        if predicate():
            return True
        time.sleep(0.01)
    return False
