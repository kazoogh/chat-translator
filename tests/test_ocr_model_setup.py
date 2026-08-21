from __future__ import annotations

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from game_chat_translator.vision import model_setup
from game_chat_translator.vision.model_setup import (
    OcrModelFile,
    OcrModelSetup,
    OcrSetupStatus,
)


@dataclass
class _Response:
    payload: bytes
    final_url: str
    total_size: int | None
    supports_resume: bool = False
    closed: bool = False

    def chunks(self, _size: int) -> Iterator[bytes]:
        midpoint = len(self.payload) // 2
        yield self.payload[:midpoint]
        yield self.payload[midpoint:]

    def close(self) -> None:
        self.closed = True


@dataclass
class _Source:
    payloads: dict[str, bytes]

    def open(self, url: str, *, offset: int) -> _Response:
        assert offset == 0
        payload = self.payloads[url]
        return _Response(payload, url, len(payload))


def _manifest() -> tuple[OcrModelFile, ...]:
    files = (
        ("det", "config.json", b"det-config"),
        ("det", "inference.json", b"det-graph"),
        ("det", "inference.pdiparams", b"det-weights"),
        ("det", "inference.yml", b"det-yaml"),
        ("rec", "config.json", b"rec-config"),
        ("rec", "inference.json", b"rec-graph"),
        ("rec", "inference.pdiparams", b"rec-weights"),
        ("rec", "inference.yml", b"rec-yaml"),
    )
    return tuple(
        OcrModelFile(
            component,
            filename,
            f"https://huggingface.co/pinned/{component}/{filename}",
            len(payload),
            hashlib.sha256(payload).hexdigest(),
        )
        for component, filename, payload in files
    )


def test_explicit_setup_verifies_and_activates_atomic_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest()
    monkeypatch.setattr(model_setup, "OCR_MODEL_FILES", manifest)
    payloads = {
        item.url: next(
            payload
            for component, filename, payload in (
                ("det", "config.json", b"det-config"),
                ("det", "inference.json", b"det-graph"),
                ("det", "inference.pdiparams", b"det-weights"),
                ("det", "inference.yml", b"det-yaml"),
                ("rec", "config.json", b"rec-config"),
                ("rec", "inference.json", b"rec-graph"),
                ("rec", "inference.pdiparams", b"rec-weights"),
                ("rec", "inference.yml", b"rec-yaml"),
            )
            if component == item.component and filename == item.filename
        )
        for item in manifest
    }
    progress: list[tuple[int, int]] = []
    setup = OcrModelSetup(tmp_path / "ocr", _Source(payloads))

    outcome = setup.install(progress=lambda received, total: progress.append((received, total)))

    assert outcome.status is OcrSetupStatus.INSTALLED
    assert setup.ready_paths() is not None
    assert progress[-1] == (sum(map(len, payloads.values())), sum(map(len, payloads.values())))
    assert setup.install().status is OcrSetupStatus.READY


def test_digest_failure_never_activates_partial_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest()
    monkeypatch.setattr(model_setup, "OCR_MODEL_FILES", manifest)
    payloads = {item.url: b"x" * item.size_bytes for item in manifest}
    setup = OcrModelSetup(tmp_path / "ocr", _Source(payloads))

    outcome = setup.install()

    assert outcome.status is OcrSetupStatus.FAILED
    assert outcome.code == "DIGEST_MISMATCH"
    assert setup.ready_paths() is None
    assert not any(path.name.startswith(".ocr-staging-") for path in (tmp_path / "ocr").iterdir())


def test_cancel_and_in_use_remove_are_explicit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest()
    monkeypatch.setattr(model_setup, "OCR_MODEL_FILES", manifest)
    setup = OcrModelSetup(tmp_path / "ocr", _Source({item.url: b"" for item in manifest}))

    assert setup.install(cancelled=lambda: True).status is OcrSetupStatus.CANCELLED
    assert setup.remove(in_use=True).code == "MODEL_IN_USE"


def test_setup_rejects_insufficient_disk_before_opening_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest()
    monkeypatch.setattr(model_setup, "OCR_MODEL_FILES", manifest)
    setup = OcrModelSetup(
        tmp_path / "ocr",
        _Source({}),
        disk_free=lambda _path: 0,
    )

    outcome = setup.install()

    assert outcome.status is OcrSetupStatus.REJECTED
    assert outcome.code == "INSUFFICIENT_DISK"
