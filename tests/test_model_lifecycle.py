from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from game_chat_translator.model_management.lifecycle import (
    DownloadCommand,
    ModelLifecycleManager,
    ModelOutcomeStatus,
)
from game_chat_translator.validation.schemas import ModelEntry


@dataclass
class FakeResponse:
    payload: bytes
    final_url: str
    total_size: int | None
    supports_resume: bool = True
    fail_after: bool = False
    closed: bool = False

    def chunks(self, size: int):  # type: ignore[no-untyped-def]
        midpoint = max(1, len(self.payload) // 2)
        yield self.payload[:midpoint]
        if self.fail_after:
            raise OSError("synthetic interruption")
        yield self.payload[midpoint:]

    def close(self) -> None:
        self.closed = True


class FakeSource:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.offsets: list[int] = []
        self.redirect: str | None = None
        self.truncate = False
        self.fail_first = False

    def open(self, url: str, *, offset: int) -> FakeResponse:
        self.offsets.append(offset)
        payload = self.payload[offset:]
        if self.truncate:
            payload = payload[:-1]
        response = FakeResponse(
            payload,
            self.redirect or url,
            len(self.payload),
            fail_after=self.fail_first and len(self.offsets) == 1,
        )
        return response


def entry(payload: bytes, *, model_id: str = "language.test") -> ModelEntry:
    return ModelEntry.model_validate(
        {
            "model_id": model_id,
            "provider": "fasttext",
            "languages": ["en", "ru", "tr"],
            "hardware_tier": "cpu_low",
            "size_bytes": len(payload),
            "license_id": "test-only",
            "source_url": "https://models.example.invalid/model.bin",
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    )


def manager(tmp_path: Path, source: FakeSource, **kwargs):  # type: ignore[no-untyped-def]
    allowed_entries = kwargs.pop("allowed_entries", (entry(source.payload),))
    return ModelLifecycleManager(
        tmp_path / "models",
        source,
        lambda _entry, path: path.read_bytes().startswith(b"healthy"),
        allowed_entries=allowed_entries,
        disk_free=lambda _path: 10**12,
        **kwargs,
    )


def test_download_verifies_and_atomically_activates_fixed_internal_name(tmp_path: Path) -> None:
    payload = b"healthy-model"
    lifecycle = manager(tmp_path, FakeSource(payload))
    outcome = lifecycle.download(DownloadCommand(entry(payload)))
    assert outcome.status is ModelOutcomeStatus.ACTIVATED
    assert outcome.path == tmp_path / "models" / "language.test.bin"
    assert outcome.path.read_bytes() == payload
    assert not (tmp_path / "models" / ".downloads" / "language.test.part").exists()


def test_truncation_and_digest_mismatch_never_activate(tmp_path: Path) -> None:
    payload = b"healthy-model"
    truncated = FakeSource(payload)
    truncated.truncate = True
    lifecycle = manager(tmp_path, truncated)
    outcome = lifecycle.download(DownloadCommand(entry(payload), max_attempts=2))
    assert outcome.code == "TRUNCATED"
    assert lifecycle.active_path("language.test") is None

    wrong = entry(payload).model_copy(update={"sha256": "0" * 64})
    outcome = manager(tmp_path / "other", FakeSource(payload), allowed_entries=(wrong,)).download(
        DownloadCommand(wrong)
    )
    assert outcome.code == "DIGEST_MISMATCH"


def test_redirect_and_manifest_path_traversal_are_rejected(tmp_path: Path) -> None:
    payload = b"healthy-model"
    source = FakeSource(payload)
    source.redirect = "https://evil.invalid/payload"
    outcome = manager(tmp_path, source).download(DownloadCommand(entry(payload)))
    assert outcome.code == "URL_CHANGED"
    assert list((tmp_path / "models").glob("*.bin")) == []

    try:
        entry(payload, model_id="../../escape")
    except ValueError:
        pass
    else:
        raise AssertionError("manifest model ID traversal was accepted")


def test_atomic_replace_and_health_failure_preserve_last_known_good(tmp_path: Path) -> None:
    old = b"healthy-old"
    lifecycle = manager(tmp_path, FakeSource(old))
    assert lifecycle.download(DownloadCommand(entry(old))).status is ModelOutcomeStatus.ACTIVATED
    active = lifecycle.active_path("language.test")
    assert active is not None

    unhealthy = b"broken-model"
    lifecycle._source.payload = unhealthy
    lifecycle._allowed["language.test"] = entry(unhealthy)
    outcome = lifecycle.download(DownloadCommand(entry(unhealthy)))
    assert outcome.code == "HEALTH_CHECK_FAILED"
    assert active.read_bytes() == old

    replacement = b"healthy-new"
    failing = manager(
        tmp_path,
        FakeSource(replacement),
        allowed_entries=(entry(replacement),),
        replace=lambda _source, _target: (_ for _ in ()).throw(OSError("rename failed")),
    )
    failing._active["language.test"] = active  # establish persisted state for this isolated fake
    outcome = failing.download(DownloadCommand(entry(replacement), max_attempts=1))
    assert outcome.code == "DOWNLOAD_FAILED"
    assert active.read_bytes() == old
    assert failing.active_path("language.test") == active


def test_cancel_retains_partial_and_next_command_resumes(tmp_path: Path) -> None:
    payload = b"healthy-" + b"x" * 100
    source = FakeSource(payload)
    checks = 0

    def cancelled() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 3

    lifecycle = manager(tmp_path, source)
    cancelled_outcome = lifecycle.download(DownloadCommand(entry(payload)), cancelled=cancelled)
    assert cancelled_outcome.status is ModelOutcomeStatus.CANCELLED
    assert cancelled_outcome.bytes_received > 0
    completed = lifecycle.download(DownloadCommand(entry(payload)))
    assert completed.status is ModelOutcomeStatus.ACTIVATED
    assert completed.resumed
    assert source.offsets[-1] > 0


def test_interrupted_transfer_retries_with_bounded_resume(tmp_path: Path) -> None:
    payload = b"healthy-" + b"z" * 50
    source = FakeSource(payload)
    source.fail_first = True
    outcome = manager(tmp_path, source).download(DownloadCommand(entry(payload), max_attempts=2))
    assert outcome.status is ModelOutcomeStatus.ACTIVATED
    assert outcome.attempts == 2
    assert outcome.resumed
    assert source.offsets[1] > 0


def test_removal_rejects_in_use_and_never_unlinks_unmanaged_path(tmp_path: Path) -> None:
    payload = b"healthy-model"
    lifecycle = manager(tmp_path, FakeSource(payload))
    lifecycle.download(DownloadCommand(entry(payload)))
    active = lifecycle.active_path("language.test")
    assert active is not None
    assert lifecycle.remove("language.test").code == "MODEL_ACTIVE"
    lifecycle.deactivate("language.test")
    lifecycle.mark_in_use("language.test", True)
    assert lifecycle.remove("language.test").code == "MODEL_IN_USE"
    assert active.exists()
    lifecycle.mark_in_use("language.test", False)
    assert lifecycle.remove("language.test").status is ModelOutcomeStatus.REMOVED
    assert not active.exists()
    assert lifecycle.remove("../../outside").code == "NOT_INSTALLED"


def test_disk_and_declared_size_checks_happen_before_source_open(tmp_path: Path) -> None:
    payload = b"healthy-model"
    source = FakeSource(payload)
    lifecycle = ModelLifecycleManager(
        tmp_path / "models",
        source,
        lambda _entry, _path: True,
        allowed_entries=(entry(payload),),
        disk_free=lambda _path: 0,
    )
    assert lifecycle.download(DownloadCommand(entry(payload))).code == "INSUFFICIENT_DISK"
    assert source.offsets == []


def test_command_must_match_trusted_allowlist_entry(tmp_path: Path) -> None:
    payload = b"healthy-model"
    allowed = entry(payload)
    untrusted = allowed.model_copy(update={"source_url": "https://other.invalid/model.bin"})
    lifecycle = manager(tmp_path, FakeSource(payload), allowed_entries=(allowed,))
    outcome = lifecycle.download(DownloadCommand(untrusted))
    assert outcome.code == "NOT_ALLOWLISTED"


class _FailingStore:
    def get(self, model_id: str):  # type: ignore[no-untyped-def]
        del model_id
        return None

    def set_active(self, record: object) -> None:
        del record
        raise OSError("synthetic persistence failure")

    def delete(self, model_id: str) -> None:
        del model_id


def test_persistence_failure_rolls_back_to_last_known_good_file(tmp_path: Path) -> None:
    old = b"healthy-old"
    root = tmp_path / "models-root"
    first = manager(root, FakeSource(old), allowed_entries=(entry(old),))
    outcome = first.download(DownloadCommand(entry(old)))
    assert outcome.path is not None and outcome.path.read_bytes() == old

    new = b"healthy-new"
    failing = ModelLifecycleManager(
        root / "models",
        FakeSource(new),
        lambda _entry, path: path.read_bytes().startswith(b"healthy"),
        allowed_entries=(entry(new),),
        disk_free=lambda _path: 10**12,
        store=_FailingStore(),
    )
    failed = failing.download(DownloadCommand(entry(new)), cancelled=lambda: False)
    assert failed.code == "DOWNLOAD_FAILED"
    assert outcome.path.read_bytes() == old


def test_planted_hardlink_partial_is_rejected_without_touching_target(tmp_path: Path) -> None:
    payload = b"healthy-model"
    source = FakeSource(payload)
    lifecycle = manager(tmp_path, source)
    downloads = tmp_path / "models" / ".downloads"
    downloads.mkdir(parents=True)
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"do-not-touch")
    os.link(outside, downloads / "language.test.part")
    outcome = lifecycle.download(DownloadCommand(entry(payload)))
    assert outcome.code == "UNSAFE_PARTIAL"
    assert outside.read_bytes() == b"do-not-touch"
    assert source.offsets == []
