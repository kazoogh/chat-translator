from __future__ import annotations

import math
import multiprocessing
import os
import socket
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Any, Protocol

_MAX_AUDIO_SECONDS = 30
_MAX_TRANSCRIPT_CHARS = 5_000


class CancellationToken(Protocol):
    @property
    def cancelled(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class PcmAudio:
    pcm_s16le: bytes
    sample_rate: int = 16_000
    channels: int = 1

    def __post_init__(self) -> None:
        if self.channels != 1:
            raise ValueError("speech audio must be mono")
        if not 8_000 <= self.sample_rate <= 48_000:
            raise ValueError("speech sample rate is outside the safe range")
        maximum = self.sample_rate * self.channels * 2 * _MAX_AUDIO_SECONDS
        if not self.pcm_s16le or len(self.pcm_s16le) > maximum or len(self.pcm_s16le) % 2:
            raise ValueError("speech audio length is outside the safe range")


class TranscriptionStatus(StrEnum):
    READY = "ready"
    CANCELLED = "cancelled"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass(frozen=True, slots=True)
class TranscriptionOutcome:
    status: TranscriptionStatus
    text: str = ""
    confidence: float = 0.0
    language: str = "en"
    error_code: str | None = None

    def __post_init__(self) -> None:
        if len(self.text) > _MAX_TRANSCRIPT_CHARS:
            raise ValueError("transcript exceeds the safe limit")
        if not math.isfinite(self.confidence) or not 0.0 <= self.confidence <= 1.0:
            raise ValueError("transcript confidence must be between zero and one")
        if self.language != "en":
            raise ValueError("only the allowlisted English reply language is supported")
        if self.status is TranscriptionStatus.READY and not self.text.strip():
            raise ValueError("ready transcription must contain text")
        if self.status is not TranscriptionStatus.READY and self.text:
            raise ValueError("failed transcription cannot carry transcript content")


WorkerTarget = Callable[[Connection, Path, str, str], None]


class IsolatedFasterWhisper:
    """Persistent local-only STT process with hard timeout and cancellation."""

    def __init__(
        self,
        model_path: Path,
        *,
        timeout_seconds: float = 20.0,
        startup_timeout_seconds: float = 30.0,
        compute_type: str = "int8",
        worker_target: WorkerTarget | None = None,
    ) -> None:
        if not 0.1 <= timeout_seconds <= 120 or not 0.1 <= startup_timeout_seconds <= 120:
            raise ValueError("speech recognition timeout is outside the safe range")
        if compute_type not in {"int8", "float16", "int8_float16"}:
            raise ValueError("speech recognition compute type is not allowlisted")
        resolved = model_path.resolve(strict=True)
        if model_path.is_symlink() or not resolved.is_dir():
            raise ValueError("speech model must be a fixed local directory")
        self._model_path = resolved
        self._timeout = timeout_seconds
        self._startup_timeout = startup_timeout_seconds
        self._compute_type = compute_type
        self._worker_target = worker_target or _faster_whisper_worker
        self._context = multiprocessing.get_context("spawn")
        self._process: Any = None
        self._connection: Any = None
        self._closed = False

    def health_check(self) -> bool:
        return not self._closed and self._ensure_worker()

    def transcribe(
        self,
        audio: PcmAudio,
        *,
        cancellation: CancellationToken | None = None,
    ) -> TranscriptionOutcome:
        if self._closed:
            return _failure(TranscriptionStatus.STOPPED, "STT_STOPPED")
        if cancellation is not None and cancellation.cancelled:
            return _failure(TranscriptionStatus.CANCELLED, "STT_CANCELLED")
        if not self._ensure_worker():
            return _failure(TranscriptionStatus.FAILED, "STT_PROVIDER_UNAVAILABLE")
        assert self._connection is not None
        try:
            self._connection.send(("transcribe", audio))
        except (BrokenPipeError, EOFError, OSError):
            self._stop_worker()
            return _failure(TranscriptionStatus.FAILED, "STT_PROVIDER_FAILED")
        deadline = time.monotonic() + self._timeout
        while True:
            if cancellation is not None and cancellation.cancelled:
                self._stop_worker()
                return _failure(TranscriptionStatus.CANCELLED, "STT_CANCELLED")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._stop_worker()
                return _failure(TranscriptionStatus.FAILED, "STT_TIMEOUT")
            try:
                if not self._connection.poll(min(remaining, 0.02)):
                    continue
                message = self._connection.recv()
            except (BrokenPipeError, EOFError, OSError):
                self._stop_worker()
                return _failure(TranscriptionStatus.FAILED, "STT_PROVIDER_FAILED")
            if isinstance(message, TranscriptionOutcome):
                return message
            self._stop_worker()
            return _failure(TranscriptionStatus.FAILED, "STT_INVALID_RESULT")

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
                target=self._worker_target,
                args=(child, self._model_path, "cpu", self._compute_type),
                name="gct-local-stt",
                daemon=True,
            )
            process.start()
            child.close()
            self._process = process
            self._connection = parent
            if not parent.poll(self._startup_timeout):
                self._stop_worker()
                return False
            if parent.recv() != ("ready", None):
                self._stop_worker()
                return False
            return True
        except (EOFError, OSError, RuntimeError, TypeError, ValueError):
            if child is not None:
                with suppress(Exception):
                    child.close()
            if parent is not None and parent is not self._connection:
                with suppress(Exception):
                    parent.close()
            if process is not None and process is not self._process and process.pid is not None:
                with suppress(Exception):
                    process.terminate()
                    process.join(timeout=1.0)
            self._stop_worker()
            return False

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


def _faster_whisper_worker(
    connection: Connection,
    model_path: Path,
    device: str,
    compute_type: str,
) -> None:
    model: Any = None
    try:
        _deny_outbound_network()
        os.environ.update(
            {
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
                "HF_DATASETS_OFFLINE": "1",
                "GCT_STT_ISOLATED": "1",
            }
        )
        from faster_whisper import WhisperModel  # type: ignore[import-not-found]

        model = WhisperModel(
            str(model_path),
            device=device,
            compute_type=compute_type,
            local_files_only=True,
        )
        connection.send(("ready", None))
        while True:
            command, payload = connection.recv()
            if command == "close":
                return
            if command != "transcribe" or not isinstance(payload, PcmAudio):
                connection.send(_failure(TranscriptionStatus.FAILED, "STT_INVALID_REQUEST"))
                continue
            try:
                connection.send(_transcribe_local(model, payload))
            except Exception:
                connection.send(_failure(TranscriptionStatus.FAILED, "STT_PROVIDER_FAILED"))
    except (EOFError, OSError):
        return
    except Exception:
        with suppress(BrokenPipeError, EOFError, OSError):
            connection.send(("failed", None))
    finally:
        model = None
        connection.close()


def _transcribe_local(model: Any, audio: PcmAudio) -> TranscriptionOutcome:
    import numpy as np

    samples = np.frombuffer(audio.pcm_s16le, dtype=np.int16).astype(np.float32) / 32768.0
    segments, info = model.transcribe(
        samples,
        language="en",
        task="transcribe",
        beam_size=5,
        vad_filter=True,
        condition_on_previous_text=False,
    )
    rendered: list[str] = []
    probabilities: list[float] = []
    length = 0
    for segment in segments:
        text = str(segment.text).strip()
        if not text:
            continue
        addition = len(text) + (1 if rendered else 0)
        if length + addition > _MAX_TRANSCRIPT_CHARS:
            raise ValueError("transcript exceeds safe limit")
        rendered.append(text)
        length += addition
        probabilities.append(max(0.0, min(1.0, math.exp(float(segment.avg_logprob)))))
    transcript = " ".join(rendered)
    if not transcript:
        return _failure(TranscriptionStatus.FAILED, "STT_NO_SPEECH")
    confidence = sum(probabilities) / len(probabilities) if probabilities else 0.0
    language = str(getattr(info, "language", "en"))
    if language != "en":
        return _failure(TranscriptionStatus.FAILED, "STT_LANGUAGE_MISMATCH")
    return TranscriptionOutcome(TranscriptionStatus.READY, transcript, confidence, "en")


class _OfflineSocket(socket.socket):
    def connect(self, address: object) -> None:
        del address
        raise OSError("outbound network is disabled in the speech provider")

    def connect_ex(self, address: object) -> int:
        del address
        raise OSError("outbound network is disabled in the speech provider")

    def sendto(self, data: object, address: object) -> int:  # type: ignore[override]
        del data, address
        raise OSError("outbound network is disabled in the speech provider")


def _deny_outbound_network() -> None:
    def denied(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise OSError("outbound network is disabled in the speech provider")

    socket.__dict__.update(
        {
            "socket": _OfflineSocket,
            "create_connection": denied,
            "getaddrinfo": denied,
            "gethostbyname": denied,
            "gethostbyname_ex": denied,
        }
    )


def _failure(status: TranscriptionStatus, code: str) -> TranscriptionOutcome:
    return TranscriptionOutcome(status=status, error_code=code)
