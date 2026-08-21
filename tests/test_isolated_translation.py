from __future__ import annotations

import socket
from dataclasses import dataclass
from multiprocessing import Event
from pathlib import Path

from game_chat_translator.translation import (
    IsolatedTranslationProvider,
    TranslationRequestBuilder,
    TranslationTimedOut,
)
from game_chat_translator.translation.base import CancellationToken, TranslationRequest


class _TestProvider:
    provider_id = "test"
    model_id = "test-model"

    def __init__(self, marker: Path, *, probe_network: bool = False) -> None:
        self._marker = marker
        self._probe_network = probe_network

    def health_check(self) -> bool:
        if self._probe_network:
            try:
                socket.create_connection(("example.invalid", 443))
            except OSError:
                return True
            return False
        return True

    def translate(
        self,
        request: TranslationRequest,
        *,
        timeout_seconds: float,
        cancellation: CancellationToken | None = None,
    ) -> str:
        del timeout_seconds, cancellation
        if self._probe_network:
            probes = (
                lambda: socket.socket().connect(("example.invalid", 443)),
                lambda: socket.socket().connect_ex(("example.invalid", 443)),
                lambda: socket.socket().sendto(b"x", ("example.invalid", 53)),
                lambda: socket.getaddrinfo("example.invalid", 443),
                lambda: socket.gethostbyname("example.invalid"),
            )
            for probe in probes:
                try:
                    probe()
                except OSError:
                    continue
                raise AssertionError("translation worker allowed an outbound network probe")
        if not self._marker.exists():
            self._marker.write_text("first worker reached inference", encoding="utf-8")
            Event().wait()
        return f"translated:{request.source_text}"

    def close(self) -> None:
        pass


@dataclass(frozen=True)
class _Factory:
    marker: Path
    probe_network: bool = False

    def __call__(self) -> _TestProvider:
        return _TestProvider(self.marker, probe_network=self.probe_network)


def _request() -> TranslationRequest:
    return TranslationRequestBuilder().build(
        "привет",
        source_language="ru",
        context_generation=1,
        glossary_generation=1,
        model_generation=1,
    )


def test_hung_provider_is_terminated_and_replacement_can_translate(tmp_path: Path) -> None:
    provider = IsolatedTranslationProvider(
        _Factory(tmp_path / "hung.marker"),
        provider_id="test",
        model_id="test-model",
        startup_timeout_seconds=2,
    )
    try:
        try:
            provider.translate(_request(), timeout_seconds=0.15)
        except TranslationTimedOut:
            pass
        else:
            raise AssertionError("hung provider did not time out")
        assert provider.translate(_request(), timeout_seconds=2) == "translated:привет"
    finally:
        provider.close()


def test_worker_process_denies_outbound_network(tmp_path: Path) -> None:
    marker = tmp_path / "already-ready.marker"
    marker.write_text("ready", encoding="utf-8")
    provider = IsolatedTranslationProvider(
        _Factory(marker, probe_network=True),
        provider_id="test",
        model_id="test-model",
        startup_timeout_seconds=2,
    )
    try:
        assert provider.health_check()
        assert provider.translate(_request(), timeout_seconds=2) == "translated:привет"
    finally:
        provider.close()


def test_failed_provider_startup_uses_bounded_backoff(tmp_path: Path) -> None:
    now = 0.0
    provider = IsolatedTranslationProvider(
        _Factory(tmp_path / "unused.marker"),
        provider_id="test",
        model_id="test-model",
        retry_backoff_seconds=5,
        maximum_backoff_seconds=20,
        monotonic=lambda: now,
    )
    calls = 0

    def unavailable() -> bool:
        nonlocal calls
        calls += 1
        return False

    provider._ensure_worker = unavailable  # type: ignore[method-assign]
    assert not provider.health_check()
    assert not provider.health_check()
    assert calls == 1
    now = 5
    assert not provider.health_check()
    assert calls == 2
