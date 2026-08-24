from __future__ import annotations

import socket
import time
from dataclasses import dataclass
from multiprocessing.connection import Connection
from pathlib import Path

import pytest

from game_chat_translator.reply.faster_whisper_stt import (
    IsolatedFasterWhisper,
    PcmAudio,
    TranscriptionOutcome,
    TranscriptionStatus,
    _deny_outbound_network,
)


def successful_worker(connection: Connection, model: Path, device: str, compute: str) -> None:
    assert model.is_dir() and device == "cpu" and compute == "int8"
    connection.send(("ready", None))
    while True:
        command, _payload = connection.recv()
        if command == "close":
            return
        connection.send(TranscriptionOutcome(TranscriptionStatus.READY, "hello", 0.9, "en"))


def hanging_worker(connection: Connection, model: Path, device: str, compute: str) -> None:
    del model, device, compute
    connection.send(("ready", None))
    connection.recv()
    time.sleep(10)


def malformed_worker(connection: Connection, model: Path, device: str, compute: str) -> None:
    del model, device, compute
    connection.send(("ready", None))
    connection.recv()
    connection.send({"text": "private transcript"})


def restarting_worker(connection: Connection, model: Path, device: str, compute: str) -> None:
    del device, compute
    marker = model / "attempted"
    connection.send(("ready", None))
    connection.recv()
    if not marker.exists():
        marker.touch()
        time.sleep(10)
        return
    connection.send(TranscriptionOutcome(TranscriptionStatus.READY, "hello", 0.9, "en"))


def network_denial_worker(connection: Connection, model: Path, device: str, compute: str) -> None:
    del model, device, compute
    _deny_outbound_network()
    probes = (
        lambda: socket.create_connection(("127.0.0.1", 9)),
        lambda: socket.getaddrinfo("example.invalid", 443),
        lambda: socket.socket().connect_ex(("127.0.0.1", 9)),
        lambda: socket.socket().sendto(b"x", ("127.0.0.1", 9)),
    )
    if any(_probe_succeeded(probe) for probe in probes):
        connection.send(("failed", None))
        return
    connection.send(("ready", None))
    while True:
        command, _payload = connection.recv()
        if command == "close":
            return
        connection.send(TranscriptionOutcome(TranscriptionStatus.READY, "hello", 0.9, "en"))


def _probe_succeeded(probe: object) -> bool:
    try:
        probe()  # type: ignore[operator]
    except OSError:
        return False
    return True


@dataclass
class Cancelled:
    cancelled: bool = True


def test_audio_is_immutable_and_bounded() -> None:
    audio = PcmAudio(b"\x00\x00" * 160)
    assert audio.sample_rate == 16_000
    with pytest.raises(ValueError):
        PcmAudio(b"")
    with pytest.raises(ValueError):
        PcmAudio(b"odd")
    with pytest.raises(ValueError):
        PcmAudio(b"\x00\x00" * (16_000 * 31))


def test_spawned_service_returns_typed_result_and_closes(tmp_path: Path) -> None:
    model = tmp_path / "model"
    model.mkdir()
    service = IsolatedFasterWhisper(model, worker_target=successful_worker)

    outcome = service.transcribe(PcmAudio(b"\x00\x00" * 160))

    assert outcome == TranscriptionOutcome(TranscriptionStatus.READY, "hello", 0.9, "en")
    service.close()
    stopped = service.transcribe(PcmAudio(b"\x00\x00"))
    assert stopped.status is TranscriptionStatus.STOPPED
    assert stopped.error_code == "STT_STOPPED"


def test_cancel_and_timeout_terminate_worker(tmp_path: Path) -> None:
    model = tmp_path / "model"
    model.mkdir()
    cancelled = IsolatedFasterWhisper(model, worker_target=successful_worker)
    assert cancelled.transcribe(PcmAudio(b"\x00\x00"), cancellation=Cancelled()).status is (
        TranscriptionStatus.CANCELLED
    )
    cancelled.close()

    timed = IsolatedFasterWhisper(
        model,
        timeout_seconds=0.15,
        startup_timeout_seconds=3,
        worker_target=hanging_worker,
    )
    assert timed.transcribe(PcmAudio(b"\x00\x00")).error_code == "STT_TIMEOUT"
    timed.close()


def test_transcription_outcome_rejects_nonfinite_or_content_bearing_failure() -> None:
    with pytest.raises(ValueError):
        TranscriptionOutcome(TranscriptionStatus.READY, "hello", float("nan"), "en")
    with pytest.raises(ValueError):
        TranscriptionOutcome(TranscriptionStatus.FAILED, "private transcript", 0, "en")


def test_malformed_worker_result_is_rejected_without_content(tmp_path: Path) -> None:
    model = tmp_path / "model"
    model.mkdir()
    service = IsolatedFasterWhisper(model, worker_target=malformed_worker)
    outcome = service.transcribe(PcmAudio(b"\0\0"))
    service.close()
    assert outcome.error_code == "STT_INVALID_RESULT"
    assert outcome.text == ""


def test_timed_out_worker_is_replaced_and_later_request_succeeds(tmp_path: Path) -> None:
    model = tmp_path / "model"
    model.mkdir()
    service = IsolatedFasterWhisper(
        model,
        timeout_seconds=0.15,
        startup_timeout_seconds=3,
        worker_target=restarting_worker,
    )
    assert service.transcribe(PcmAudio(b"\0\0")).error_code == "STT_TIMEOUT"
    assert service.transcribe(PcmAudio(b"\0\0")).status is TranscriptionStatus.READY
    service.close()


def test_isolated_worker_denies_socket_dns_and_datagram_paths(tmp_path: Path) -> None:
    model = tmp_path / "model"
    model.mkdir()
    service = IsolatedFasterWhisper(model, worker_target=network_denial_worker)
    assert service.transcribe(PcmAudio(b"\0\0")).status is TranscriptionStatus.READY
    service.close()
