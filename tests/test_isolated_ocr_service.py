from __future__ import annotations

import socket
from dataclasses import dataclass
from threading import Event

from game_chat_translator.models import OcrFragment, Point
from game_chat_translator.vision.base import OcrInput, OcrProviderError, ProviderHealth
from game_chat_translator.vision.isolated_service import IsolatedOcrService
from game_chat_translator.vision.ocr_service import EventCancellationToken


class BlockingTestProvider:
    health = ProviderHealth.READY

    def health_check(self) -> bool:
        return True

    def recognize(self, request: OcrInput, cancellation: object = None) -> tuple[OcrFragment, ...]:
        del cancellation
        if request.pixels == b"\x00":
            Event().wait()
        if request.pixels == b"\x02":
            raise OcrProviderError("private provider detail")
        if request.pixels == b"\x03":
            try:
                socket.create_connection(("127.0.0.1", 9), timeout=0.01)
            except OSError as exc:
                if "outbound network is disabled" not in str(exc):
                    raise
            else:
                raise AssertionError("OCR worker unexpectedly opened a network connection")
        return (
            OcrFragment(
                text="recovered",
                confidence=1.0,
                polygon=(Point(x=0, y=0),) * 4,
                script="latin",
            ),
        )

    def close(self) -> None:
        self.health = ProviderHealth.STOPPED


@dataclass(frozen=True)
class BlockingTestProviderFactory:
    def __call__(self) -> BlockingTestProvider:
        return BlockingTestProvider()


def test_hung_provider_is_terminated_and_next_request_uses_fresh_worker() -> None:
    service = IsolatedOcrService(BlockingTestProviderFactory(), timeout_seconds=1.0)
    timed_out = service.recognize(OcrInput(b"\x00", 1, 1, 1, 1), generation=lambda: 1)
    assert timed_out.error_code == "OCR_TIMEOUT"

    recovered = service.recognize(OcrInput(b"\x01", 1, 1, 1, 1), generation=lambda: 1)
    assert recovered.error_code is None
    assert recovered.fragments[0].text == "recovered"
    service.close()
    assert (
        service.recognize(OcrInput(b"\x01", 1, 1, 1, 1), generation=lambda: 1).error_code
        == "OCR_STOPPED"
    )


def test_isolated_service_checks_live_generation_and_cancellation_before_publish() -> None:
    service = IsolatedOcrService(BlockingTestProviderFactory(), timeout_seconds=1.0)
    generation_calls = 0

    def changing_generation() -> int:
        nonlocal generation_calls
        generation_calls += 1
        return 3 if generation_calls == 1 else 4

    obsolete = service.recognize(OcrInput(b"\x01", 1, 1, 1, 3), generation=changing_generation)
    assert obsolete.error_code == "OCR_OBSOLETE_GENERATION"
    assert obsolete.fragments == ()

    token = EventCancellationToken()
    token.cancel()
    cancelled = service.recognize(
        OcrInput(b"\x01", 1, 1, 1, 4), generation=lambda: 4, cancellation=token
    )
    assert cancelled.error_code == "OCR_CANCELLED"
    service.close()


def test_isolated_service_redacts_provider_exception_details() -> None:
    service = IsolatedOcrService(BlockingTestProviderFactory(), timeout_seconds=1.0)
    outcome = service.recognize(OcrInput(b"\x02", 1, 1, 1, 1), generation=lambda: 1)
    assert outcome.error_code == "OCR_PROVIDER_FAILED"
    assert "private provider detail" not in repr(outcome)
    service.close()


def test_isolated_service_denies_outbound_network_inside_provider_process() -> None:
    service = IsolatedOcrService(BlockingTestProviderFactory(), timeout_seconds=1.0)
    outcome = service.recognize(OcrInput(b"\x03", 1, 1, 1, 1), generation=lambda: 1)
    assert outcome.error_code is None
    assert outcome.fragments[0].text == "recovered"
    service.close()


def test_unpicklable_worker_factory_degrades_without_escaping() -> None:
    service = IsolatedOcrService(lambda: BlockingTestProvider(), timeout_seconds=0.2)
    outcome = service.recognize(OcrInput(b"\x01", 1, 1, 1, 1), generation=lambda: 1)
    assert outcome.error_code == "OCR_PROVIDER_FAILED"
    service.close()
