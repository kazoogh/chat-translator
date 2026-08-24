from __future__ import annotations

import time
from collections.abc import Callable
from contextlib import suppress
from threading import Lock, get_ident
from typing import Any, Protocol, cast

from game_chat_translator.reply.base import AudioBuffer


class AudioRecorderError(RuntimeError):
    """Safe microphone failure that never embeds captured audio or device details."""


class _InputStream(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...

    def close(self) -> None: ...


class SoundDeviceAudioRecorder:
    """Single-owner, fixed-format microphone recorder with bounded in-memory PCM."""

    def __init__(
        self,
        *,
        sample_rate_hz: int = 16_000,
        channels: int = 1,
        maximum_seconds: float = 30.0,
        block_frames: int = 1_600,
        device: str | int | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        stream_factory: Callable[..., _InputStream] | None = None,
    ) -> None:
        if sample_rate_hz != 16_000 or channels != 1:
            raise ValueError("reply audio must use 16 kHz mono PCM")
        if not 1 <= maximum_seconds <= 30 or block_frames <= 0:
            raise ValueError("reply audio bounds are invalid")
        self._sample_rate = sample_rate_hz
        self._channels = channels
        self._maximum_bytes = int(sample_rate_hz * channels * 2 * maximum_seconds)
        self._block_frames = block_frames
        self._device = device
        self._monotonic = monotonic
        self._stream_factory = stream_factory
        self._owner: int | None = None
        self._stream: _InputStream | None = None
        self._started = 0.0
        self._chunks: list[bytes] = []
        self._size = 0
        self._overflowed = False
        self._closed = False
        self._buffer_lock = Lock()

    def begin(self) -> None:
        self._assert_owner()
        if self._closed:
            raise AudioRecorderError("MICROPHONE_CLOSED")
        if self._stream is not None:
            raise AudioRecorderError("RECORDING_ALREADY_ACTIVE")
        with self._buffer_lock:
            self._chunks.clear()
            self._size = 0
            self._overflowed = False
        factory = self._stream_factory or _sounddevice_stream_factory
        try:
            stream = factory(
                samplerate=self._sample_rate,
                channels=self._channels,
                dtype="int16",
                blocksize=self._block_frames,
                device=self._device,
                callback=self._on_audio,
            )
            stream.start()
        except Exception as exc:
            self._release_stream(locals().get("stream"))
            raise AudioRecorderError("MICROPHONE_UNAVAILABLE") from exc
        self._stream = stream
        self._started = self._monotonic()

    def finish(self) -> AudioBuffer:
        self._assert_owner()
        if self._stream is None:
            raise AudioRecorderError("RECORDING_NOT_ACTIVE")
        ended = self._monotonic()
        self._stop_stream()
        with self._buffer_lock:
            pcm = b"".join(self._chunks)
            overflowed = self._overflowed
            self._clear_buffer()
        if overflowed:
            raise AudioRecorderError("RECORDING_TOO_LONG")
        if not pcm:
            raise AudioRecorderError("RECORDING_EMPTY")
        return AudioBuffer(pcm, self._sample_rate, self._channels, self._started, ended)

    def cancel(self) -> None:
        self._assert_owner()
        self._stop_stream()
        with self._buffer_lock:
            self._clear_buffer()

    def close(self) -> None:
        self._assert_owner()
        if self._closed:
            return
        self.cancel()
        self._closed = True

    def _on_audio(self, data: Any, _frames: int, _time_info: Any, status: Any) -> None:
        if status:
            with self._buffer_lock:
                self._overflowed = True
            return
        try:
            chunk = bytes(data)
        except Exception:
            with self._buffer_lock:
                self._overflowed = True
            return
        with self._buffer_lock:
            remaining = self._maximum_bytes - self._size
            if remaining <= 0 or len(chunk) > remaining:
                self._overflowed = True
                return
            self._chunks.append(chunk)
            self._size += len(chunk)

    def _assert_owner(self) -> None:
        current = get_ident()
        if self._owner is None:
            self._owner = current
        elif self._owner != current:
            raise AudioRecorderError("MICROPHONE_WRONG_THREAD")

    def _stop_stream(self) -> None:
        stream, self._stream = self._stream, None
        self._release_stream(stream)

    @staticmethod
    def _release_stream(stream: object | None) -> None:
        if stream is None:
            return
        for operation in ("stop", "close"):
            with suppress(Exception):
                getattr(stream, operation)()

    def _clear_buffer(self) -> None:
        self._chunks.clear()
        self._size = 0
        self._overflowed = False


def _sounddevice_stream_factory(**kwargs: object) -> _InputStream:
    import sounddevice

    return cast(_InputStream, sounddevice.RawInputStream(**kwargs))
