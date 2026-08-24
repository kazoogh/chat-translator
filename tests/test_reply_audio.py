from __future__ import annotations

from threading import Thread

import pytest

from game_chat_translator.reply.audio import AudioRecorderError, SoundDeviceAudioRecorder


class _Stream:
    def __init__(self, callback: object) -> None:
        self.callback = callback
        self.started = False
        self.stopped = False
        self.closed = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def close(self) -> None:
        self.closed = True


def test_recorder_keeps_fixed_pcm_in_memory_and_releases_stream() -> None:
    times = iter((10.0, 10.5))
    streams: list[_Stream] = []

    def factory(**kwargs: object) -> _Stream:
        stream = _Stream(kwargs["callback"])
        streams.append(stream)
        return stream

    recorder = SoundDeviceAudioRecorder(monotonic=lambda: next(times), stream_factory=factory)
    recorder.begin()
    streams[0].callback(b"\x01\x00" * 160, 160, None, None)  # type: ignore[operator]
    result = recorder.finish()

    assert result.pcm == b"\x01\x00" * 160
    assert (result.sample_rate_hz, result.channels) == (16_000, 1)
    assert streams[0].stopped and streams[0].closed


def test_cancel_discards_audio_and_close_is_idempotent() -> None:
    streams: list[_Stream] = []

    def factory(**kwargs: object) -> _Stream:
        stream = _Stream(kwargs["callback"])
        streams.append(stream)
        return stream

    recorder = SoundDeviceAudioRecorder(stream_factory=factory)
    recorder.begin()
    streams[0].callback(b"private", 1, None, None)  # type: ignore[operator]
    recorder.cancel()
    recorder.close()
    recorder.close()
    with pytest.raises(AudioRecorderError, match="MICROPHONE_CLOSED"):
        recorder.begin()


def test_overflow_fails_safely_without_returning_partial_audio() -> None:
    streams: list[_Stream] = []

    def factory(**kwargs: object) -> _Stream:
        stream = _Stream(kwargs["callback"])
        streams.append(stream)
        return stream

    recorder = SoundDeviceAudioRecorder(maximum_seconds=1, stream_factory=factory)
    recorder.begin()
    streams[0].callback(b"x" * 32_001, 1, None, None)  # type: ignore[operator]
    with pytest.raises(AudioRecorderError, match="RECORDING_TOO_LONG"):
        recorder.finish()


def test_device_operations_are_rejected_from_a_second_thread() -> None:
    recorder = SoundDeviceAudioRecorder(stream_factory=lambda **kwargs: _Stream(kwargs["callback"]))
    recorder.begin()
    errors: list[Exception] = []
    thread = Thread(target=lambda: _capture_error(recorder, errors))
    thread.start()
    thread.join()
    recorder.cancel()
    assert isinstance(errors[0], AudioRecorderError)


def _capture_error(recorder: SoundDeviceAudioRecorder, errors: list[Exception]) -> None:
    try:
        recorder.cancel()
    except Exception as exc:
        errors.append(exc)
