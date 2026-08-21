from __future__ import annotations

import multiprocessing
import os
import socket
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Any, Protocol

from game_chat_translator.models import OcrFragment
from game_chat_translator.vision.base import (
    CancellationToken,
    OcrCancelled,
    OcrInput,
    OcrOutcome,
    OcrProvider,
    ProviderHealth,
)
from game_chat_translator.vision.ocr_service import OcrProviderRouter
from game_chat_translator.vision.paddle_ocr import PaddleOcrConfig, PaddleOcrProvider


class OcrProviderFactory(Protocol):
    def __call__(self) -> OcrProvider: ...


@dataclass(frozen=True, slots=True)
class PaddleOcrProviderFactory:
    detection_model_dir: Path
    recognition_model_dir: Path
    language: str = "ru"
    device: str = "cpu"
    minimum_confidence: float = 0.45

    def __call__(self) -> OcrProvider:
        return PaddleOcrProvider(
            PaddleOcrConfig(
                self.detection_model_dir,
                self.recognition_model_dir,
                self.language,
                self.device,
                self.minimum_confidence,
            )
        )


@dataclass(frozen=True, slots=True)
class PaddleOcrRouterFactory:
    preferred: PaddleOcrProviderFactory
    cpu_fallback: PaddleOcrProviderFactory

    def __call__(self) -> OcrProvider:
        return OcrProviderRouter(self.preferred(), self.cpu_fallback())


class IsolatedOcrService:
    """Persistent provider subprocess that can be terminated after timeout/cancellation."""

    def __init__(self, factory: OcrProviderFactory, *, timeout_seconds: float = 5.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("OCR timeout must be positive")
        self._factory = factory
        self._timeout = timeout_seconds
        self._context = multiprocessing.get_context("spawn")
        self._process: Any = None
        self._connection: Any = None
        self._closed = False

    def recognize(
        self,
        request: OcrInput,
        *,
        generation: Callable[[], int],
        cancellation: CancellationToken | None = None,
    ) -> OcrOutcome:
        if self._closed:
            return OcrOutcome((), ProviderHealth.STOPPED, request.generation, "OCR_STOPPED")
        if cancellation is not None and cancellation.cancelled:
            return OcrOutcome((), ProviderHealth.DEGRADED, request.generation, "OCR_CANCELLED")
        if request.generation != generation():
            return OcrOutcome(
                (), ProviderHealth.DEGRADED, request.generation, "OCR_OBSOLETE_GENERATION"
            )
        if not self._ensure_worker():
            return OcrOutcome(
                (), ProviderHealth.DEGRADED, request.generation, "OCR_PROVIDER_FAILED"
            )
        assert self._connection is not None
        try:
            self._connection.send(("recognize", request))
        except (BrokenPipeError, EOFError, OSError):
            self._stop_worker()
            return OcrOutcome(
                (), ProviderHealth.DEGRADED, request.generation, "OCR_PROVIDER_FAILED"
            )
        deadline = time.monotonic() + self._timeout
        while True:
            if cancellation is not None and cancellation.cancelled:
                self._stop_worker()
                return OcrOutcome((), ProviderHealth.DEGRADED, request.generation, "OCR_CANCELLED")
            if request.generation != generation():
                self._stop_worker()
                return OcrOutcome(
                    (), ProviderHealth.DEGRADED, request.generation, "OCR_OBSOLETE_GENERATION"
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._stop_worker()
                return OcrOutcome((), ProviderHealth.DEGRADED, request.generation, "OCR_TIMEOUT")
            try:
                if not self._connection.poll(min(remaining, 0.02)):
                    continue
                status, payload = self._connection.recv()
            except (BrokenPipeError, EOFError, OSError):
                self._stop_worker()
                return OcrOutcome(
                    (), ProviderHealth.DEGRADED, request.generation, "OCR_PROVIDER_FAILED"
                )
            if (
                status == "ok"
                and isinstance(payload, tuple)
                and all(isinstance(item, OcrFragment) for item in payload)
            ):
                return OcrOutcome(payload, ProviderHealth.READY, request.generation)
            error_code = "OCR_CANCELLED" if status == "cancelled" else "OCR_PROVIDER_FAILED"
            return OcrOutcome((), ProviderHealth.DEGRADED, request.generation, error_code)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop_worker()

    def _ensure_worker(self) -> bool:
        if self._process is not None and self._process.is_alive():
            return True
        self._stop_worker()
        parent: Any = None
        child: Any = None
        process: Any = None
        try:
            parent, child = self._context.Pipe()
            process = self._context.Process(
                target=_provider_worker,
                args=(child, self._factory),
                name="gct-ocr-provider",
                daemon=True,
            )
            process.start()
            child.close()
        except Exception:
            if child is not None:
                with suppress(Exception):
                    child.close()
            if parent is not None:
                with suppress(Exception):
                    parent.close()
            if process is not None and process.pid is not None:
                with suppress(Exception):
                    process.terminate()
                    process.join(timeout=1.0)
            return False
        self._process = process
        self._connection = parent
        try:
            if not parent.poll(self._timeout):
                self._stop_worker()
                return False
            message = parent.recv()
            if not isinstance(message, tuple) or len(message) != 2:
                self._stop_worker()
                return False
            status, _payload = message
        except (EOFError, OSError, TypeError, ValueError):
            self._stop_worker()
            return False
        if status != "ready":
            self._stop_worker()
            return False
        return True

    def _stop_worker(self) -> None:
        connection, self._connection = self._connection, None
        process, self._process = self._process, None
        if connection is not None:
            with suppress(BrokenPipeError, EOFError, OSError):
                connection.send(("close", None))
            connection.close()
        if process is None:
            return
        process.join(timeout=0.2)
        if process.is_alive():
            process.terminate()
            process.join(timeout=1.0)
        if process.is_alive():
            process.kill()
            process.join(timeout=1.0)


def _provider_worker(connection: Connection, factory: OcrProviderFactory) -> None:
    provider: OcrProvider | None = None
    try:
        _deny_outbound_network()
        os.environ["GCT_OCR_ISOLATED"] = "1"
        provider = factory()
        if not provider.health_check():
            connection.send(("failed", None))
            return
        connection.send(("ready", None))
        while True:
            command, payload = connection.recv()
            if command == "close":
                return
            if command != "recognize" or not isinstance(payload, OcrInput):
                connection.send(("failed", None))
                continue
            try:
                fragments = provider.recognize(payload)
            except OcrCancelled:
                connection.send(("cancelled", None))
            except Exception:
                connection.send(("failed", None))
            else:
                connection.send(("ok", fragments))
    except (EOFError, OSError):
        return
    except Exception:
        with suppress(BrokenPipeError, EOFError, OSError):
            connection.send(("failed", None))
    finally:
        if provider is not None:
            with suppress(Exception):
                provider.close()
        connection.close()


class _OfflineSocket(socket.socket):
    def connect(self, address: object) -> None:
        del address
        raise OSError("outbound network is disabled in the OCR provider")

    def connect_ex(self, address: object) -> int:
        del address
        raise OSError("outbound network is disabled in the OCR provider")

    def sendto(self, data: object, address: object) -> int:  # type: ignore[override]
        del data, address
        raise OSError("outbound network is disabled in the OCR provider")


def _deny_outbound_network() -> None:
    def denied(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise OSError("outbound network is disabled in the OCR provider")

    socket.__dict__.update(
        {
            "socket": _OfflineSocket,
            "create_connection": denied,
            "getaddrinfo": denied,
            "gethostbyname": denied,
            "gethostbyname_ex": denied,
        }
    )
