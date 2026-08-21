from __future__ import annotations

import multiprocessing
import socket
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Any, Protocol

from game_chat_translator.translation.argos_translate import ArgosTranslationProvider
from game_chat_translator.translation.base import (
    CancellationToken,
    TranslationCancelled,
    TranslationProvider,
    TranslationProviderError,
    TranslationRequest,
    TranslationTimedOut,
)
from game_chat_translator.translation.llama_cpp_local import LlamaCppTranslationProvider


class TranslationProviderFactory(Protocol):
    def __call__(self) -> TranslationProvider: ...


@dataclass(frozen=True, slots=True)
class LlamaCppProviderFactory:
    model_path: Path
    model_id: str
    context_size: int = 2_048
    maximum_output_tokens: int = 384

    def __call__(self) -> TranslationProvider:
        return LlamaCppTranslationProvider(
            self.model_path,
            model_id=self.model_id,
            context_size=self.context_size,
            maximum_output_tokens=self.maximum_output_tokens,
        )


@dataclass(frozen=True, slots=True)
class ArgosProviderFactory:
    def __call__(self) -> TranslationProvider:
        return ArgosTranslationProvider()


class IsolatedTranslationProvider:
    """Persistent offline subprocess with a hard timeout/cancellation boundary."""

    def __init__(
        self,
        factory: TranslationProviderFactory,
        *,
        provider_id: str,
        model_id: str | None,
        startup_timeout_seconds: float = 30.0,
        retry_backoff_seconds: float = 5.0,
        maximum_backoff_seconds: float = 60.0,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if (
            startup_timeout_seconds <= 0
            or retry_backoff_seconds <= 0
            or maximum_backoff_seconds < retry_backoff_seconds
        ):
            raise ValueError("provider timeout/backoff bounds are invalid")
        self._factory = factory
        self.provider_id = provider_id
        self.model_id = model_id
        self._startup_timeout = startup_timeout_seconds
        self._retry_backoff = retry_backoff_seconds
        self._maximum_backoff = maximum_backoff_seconds
        self._monotonic = monotonic
        self._failures = 0
        self._retry_after = 0.0
        self._context = multiprocessing.get_context("spawn")
        self._process: Any = None
        self._connection: Any = None
        self._closed = False

    def health_check(self) -> bool:
        if self._closed or self._monotonic() < self._retry_after:
            return False
        if self._ensure_worker():
            self._failures = 0
            self._retry_after = 0.0
            return True
        self._record_failure()
        return False

    def translate(
        self,
        request: TranslationRequest,
        *,
        timeout_seconds: float,
        cancellation: CancellationToken | None = None,
    ) -> str:
        if self._closed:
            raise TranslationProviderError("translation provider is stopped")
        if cancellation is not None and cancellation.cancelled:
            raise TranslationCancelled("translation was cancelled")
        if self._monotonic() < self._retry_after:
            raise TranslationProviderError("translation provider is in retry backoff")
        if not self._ensure_worker():
            self._record_failure()
            raise TranslationProviderError("translation provider could not start")
        assert self._connection is not None
        try:
            self._connection.send(("translate", request, timeout_seconds))
        except (BrokenPipeError, EOFError, OSError) as exc:
            self._stop_worker()
            raise TranslationProviderError("translation provider stopped unexpectedly") from exc
        deadline = time.monotonic() + timeout_seconds
        while True:
            if cancellation is not None and cancellation.cancelled:
                self._stop_worker()
                raise TranslationCancelled("translation was cancelled")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._stop_worker()
                raise TranslationTimedOut("translation timed out")
            try:
                if not self._connection.poll(min(remaining, 0.02)):
                    continue
                message = self._connection.recv()
            except (BrokenPipeError, EOFError, OSError) as exc:
                self._stop_worker()
                raise TranslationProviderError("translation provider stopped unexpectedly") from exc
            if not isinstance(message, tuple) or len(message) != 2:
                self._stop_worker()
                raise TranslationProviderError("translation provider returned invalid data")
            status, payload = message
            if status == "ok" and isinstance(payload, str):
                return payload
            if status == "cancelled":
                raise TranslationCancelled("translation was cancelled")
            raise TranslationProviderError("translation provider failed")

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
                name="gct-translation-provider",
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
            if not parent.poll(self._startup_timeout):
                self._stop_worker()
                return False
            message = parent.recv()
        except (EOFError, OSError, TypeError, ValueError):
            self._stop_worker()
            return False
        if not isinstance(message, tuple) or len(message) != 2 or message[0] != "ready":
            self._stop_worker()
            return False
        return True

    def _stop_worker(self) -> None:
        connection, self._connection = self._connection, None
        process, self._process = self._process, None
        if connection is not None:
            with suppress(BrokenPipeError, EOFError, OSError):
                connection.send(("close", None, None))
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

    def _record_failure(self) -> None:
        self._failures += 1
        delay = min(
            self._maximum_backoff,
            self._retry_backoff * (2 ** min(self._failures - 1, 8)),
        )
        self._retry_after = self._monotonic() + delay


def _provider_worker(connection: Connection, factory: TranslationProviderFactory) -> None:
    provider: TranslationProvider | None = None
    try:
        _deny_outbound_network()
        provider = factory()
        if not provider.health_check():
            connection.send(("failed", None))
            return
        connection.send(("ready", None))
        while True:
            command, payload, timeout = connection.recv()
            if command == "close":
                return
            if command != "translate" or not isinstance(payload, TranslationRequest):
                connection.send(("failed", None))
                continue
            try:
                output = provider.translate(payload, timeout_seconds=float(timeout))
            except TranslationCancelled:
                connection.send(("cancelled", None))
            except Exception:
                connection.send(("failed", None))
            else:
                connection.send(("ok", output))
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
        raise OSError("outbound network is disabled in the translation provider")

    def connect_ex(self, address: object) -> int:
        del address
        raise OSError("outbound network is disabled in the translation provider")

    def sendto(self, data: object, address: object) -> int:  # type: ignore[override]
        del data, address
        raise OSError("outbound network is disabled in the translation provider")


def _deny_outbound_network() -> None:
    def denied(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise OSError("outbound network is disabled in the translation provider")

    socket.__dict__.update(
        {
            "socket": _OfflineSocket,
            "create_connection": denied,
            "getaddrinfo": denied,
            "gethostbyname": denied,
            "gethostbyname_ex": denied,
        }
    )
