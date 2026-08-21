from __future__ import annotations

from dataclasses import dataclass

import pytest

from game_chat_translator.models import OcrFragment, Point
from game_chat_translator.vision.base import (
    CancellationToken,
    OcrCancelled,
    OcrInput,
    OcrProviderError,
    ProviderHealth,
)
from game_chat_translator.vision.ocr_service import OcrProviderRouter


@dataclass
class FakeProvider:
    healthy: bool = True
    fail_recognition: bool = False
    health: ProviderHealth = ProviderHealth.UNINITIALIZED
    calls: int = 0
    closes: int = 0

    def health_check(self) -> bool:
        self.health = ProviderHealth.READY if self.healthy else ProviderHealth.FAILED
        return self.healthy

    def recognize(self, request: OcrInput, cancellation: object = None) -> tuple[OcrFragment, ...]:
        del request, cancellation
        self.calls += 1
        if self.fail_recognition:
            raise OcrProviderError("safe provider failure")
        self.health = ProviderHealth.READY
        return (
            OcrFragment(
                text="result",
                confidence=0.9,
                polygon=(Point(x=0, y=0),) * 4,
                script="latin",
            ),
        )

    def close(self) -> None:
        self.closes += 1
        self.health = ProviderHealth.STOPPED


def _request(generation: int = 1) -> OcrInput:
    return OcrInput(b"\x00", 1, 1, 1, generation)


def test_router_fails_from_accelerated_provider_to_cpu_exactly_once() -> None:
    preferred = FakeProvider(fail_recognition=True)
    cpu = FakeProvider()
    router = OcrProviderRouter(preferred, cpu)

    assert router.health_check()
    assert router.recognize(_request())[0].text == "result"
    assert preferred.calls == 1
    assert preferred.closes == 1
    assert cpu.calls == 1
    assert router.recognize(_request())[0].text == "result"
    assert preferred.calls == 1


def test_router_never_fails_over_a_cancelled_request() -> None:
    class CancelProvider(FakeProvider):
        def recognize(
            self, request: OcrInput, cancellation: CancellationToken | None = None
        ) -> tuple[OcrFragment, ...]:
            del request, cancellation
            self.calls += 1
            raise OcrCancelled("cancelled")

    preferred = CancelProvider()
    cpu = FakeProvider()
    router = OcrProviderRouter(preferred, cpu)
    router.health_check()
    with pytest.raises(OcrCancelled):
        router.recognize(_request())
    assert preferred.calls == 1
    assert cpu.calls == 0
