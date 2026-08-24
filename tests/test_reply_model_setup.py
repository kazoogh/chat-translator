from __future__ import annotations

import hashlib
from collections.abc import Iterator
from pathlib import Path

import pytest

from game_chat_translator.reply.model_setup import (
    SttModelFile,
    SttModelSetup,
    SttSetupStatus,
)


class Response:
    def __init__(self, url: str, body: bytes) -> None:
        self.final_url = url
        self.total_size = len(body)
        self.supports_resume = False
        self._body = body
        self.closed = False

    def chunks(self, size: int) -> Iterator[bytes]:
        yield from (self._body[index : index + size] for index in range(0, len(self._body), size))

    def close(self) -> None:
        self.closed = True


class Source:
    def __init__(self, bodies: dict[str, bytes]) -> None:
        self.bodies = bodies
        self.opened: list[Response] = []

    def open(self, url: str, *, offset: int) -> Response:
        assert offset == 0
        response = Response(url, self.bodies[url])
        self.opened.append(response)
        return response


def manifest(body: bytes = b"verified") -> tuple[SttModelFile, ...]:
    return (SttModelFile("model.bin", len(body), hashlib.sha256(body).hexdigest()),)


def test_installs_verified_bundle_and_removes_only_when_not_in_use(tmp_path: Path) -> None:
    files = manifest()
    source = Source({files[0].url: b"verified"})
    setup = SttModelSetup(
        tmp_path / "models",
        source,
        files=files,
        disk_free=lambda _path: 10**9,
        health_check=lambda path: (path / "model.bin").read_bytes() == b"verified",
    )

    outcome = setup.install()

    assert outcome.status is SttSetupStatus.INSTALLED
    assert setup.ready_path() is not None
    assert all(item.closed for item in source.opened)
    assert setup.remove(in_use=True).code == "MODEL_IN_USE"
    assert setup.remove(in_use=False).status is SttSetupStatus.REMOVED


def test_rejects_disk_digest_and_cancellation_without_activation(tmp_path: Path) -> None:
    files = manifest()
    low_disk = SttModelSetup(
        tmp_path / "low", Source({files[0].url: b"verified"}), files=files, disk_free=lambda _: 0
    )
    assert low_disk.install().code == "INSUFFICIENT_DISK"

    bad = SttModelSetup(
        tmp_path / "bad",
        Source({files[0].url: b"tampered"}),
        files=files,
        disk_free=lambda _: 10**9,
    )
    assert bad.install().code == "DIGEST_MISMATCH"
    assert bad.ready_path() is None

    cancelled = SttModelSetup(
        tmp_path / "cancel",
        Source({files[0].url: b"verified"}),
        files=files,
        disk_free=lambda _: 10**9,
    )
    assert cancelled.install(cancelled=lambda: True).status is SttSetupStatus.CANCELLED
    assert cancelled.ready_path() is None


def test_health_and_atomic_failure_preserve_last_known_good(tmp_path: Path) -> None:
    old_files = manifest(b"old")
    root = tmp_path / "models"
    first = SttModelSetup(
        root,
        Source({old_files[0].url: b"old"}),
        files=old_files,
        disk_free=lambda _: 10**9,
        health_check=lambda _path: True,
    )
    assert first.install().status is SttSetupStatus.INSTALLED

    new_files = manifest(b"new")

    def fail_staging(source: Path, destination: Path) -> None:
        if source.name.startswith(".stt-staging-"):
            raise OSError("injected rename failure")
        source.replace(destination)

    replacement = SttModelSetup(
        root,
        Source({new_files[0].url: b"new"}),
        files=new_files,
        disk_free=lambda _: 10**9,
        health_check=lambda _path: True,
        replace=fail_staging,
    )
    assert replacement.install().status is SttSetupStatus.FAILED
    assert (first.ready_path() / "model.bin").read_bytes() == b"old"  # type: ignore[operator]

    unhealthy = SttModelSetup(
        tmp_path / "unhealthy",
        Source({new_files[0].url: b"new"}),
        files=new_files,
        disk_free=lambda _: 10**9,
        health_check=lambda _path: False,
    )
    assert unhealthy.install().code == "HEALTH_CHECK_FAILED"
    assert unhealthy.ready_path() is None


def test_symlinked_model_root_is_rejected_before_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    linked = tmp_path / "linked"
    linked.mkdir()
    original = Path.is_symlink
    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda path: path == linked or original(path),
    )
    files = manifest()
    setup = SttModelSetup(
        linked,
        Source({files[0].url: b"verified"}),
        files=files,
        disk_free=lambda _: 10**9,
    )
    assert setup.install().code == "SETUP_FAILED"
    assert tuple(linked.iterdir()) == ()
