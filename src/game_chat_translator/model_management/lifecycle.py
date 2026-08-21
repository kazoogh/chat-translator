from __future__ import annotations

import hashlib
import os
import shutil
import stat
from collections.abc import Callable, Iterator
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import BinaryIO, Protocol

from game_chat_translator.validation.schemas import ModelEntry

_MAX_MODEL_BYTES = 16 * 1024 * 1024 * 1024
_COPY_CHUNK_BYTES = 1024 * 1024


class ModelSource(Protocol):
    """Injected content source. Implementations must not follow redirects silently."""

    def open(self, url: str, *, offset: int) -> DownloadResponse: ...


class DownloadResponse(Protocol):
    final_url: str
    total_size: int | None
    supports_resume: bool

    def chunks(self, size: int) -> Iterator[bytes]: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class InstalledModelRecord:
    model_id: str
    provider: str
    path: str
    sha256: str
    size_bytes: int
    license_id: str
    active: bool
    health_state: str


class ModelStateStore(Protocol):
    def get(self, model_id: str) -> InstalledModelRecord | None: ...

    def set_active(self, record: InstalledModelRecord) -> None: ...

    def delete(self, model_id: str) -> None: ...


class ModelOutcomeStatus(StrEnum):
    ACTIVATED = "activated"
    CANCELLED = "cancelled"
    FAILED = "failed"
    REMOVED = "removed"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class DownloadCommand:
    entry: ModelEntry
    max_attempts: int = 3
    allow_resume: bool = True

    def __post_init__(self) -> None:
        if not 1 <= self.max_attempts <= 5:
            raise ValueError("download attempts must be between one and five")


@dataclass(frozen=True, slots=True)
class ModelOutcome:
    status: ModelOutcomeStatus
    model_id: str
    code: str
    message: str
    path: Path | None = None
    bytes_received: int = 0
    attempts: int = 0
    resumed: bool = False


class ModelLifecycleManager:
    def __init__(
        self,
        root: Path,
        source: ModelSource,
        health_check: Callable[[ModelEntry, Path], bool],
        *,
        allowed_entries: tuple[ModelEntry, ...],
        replace: Callable[[Path, Path], None] = os.replace,
        disk_free: Callable[[Path], int] | None = None,
        store: ModelStateStore | None = None,
    ) -> None:
        self._root = root.resolve()
        self._downloads = self._root / ".downloads"
        self._source = source
        self._health_check = health_check
        self._allowed = {entry.model_id: entry for entry in allowed_entries}
        if len(self._allowed) != len(allowed_entries):
            raise ValueError("model allowlist contains duplicate IDs")
        self._replace = replace
        self._disk_free = disk_free or (lambda path: shutil.disk_usage(path).free)
        self._store = store
        self._installed: dict[str, Path] = {}
        self._active: dict[str, Path] = {}
        self._in_use: dict[str, int] = {}

    def active_path(self, model_id: str) -> Path | None:
        return self._active.get(model_id)

    def restore(self, entry: ModelEntry) -> bool:
        """Restore a persisted model only after containment, digest, and health validation."""
        if self._store is None:
            return False
        record = self._store.get(entry.model_id)
        if record is None or not record.active:
            return False
        path = Path(record.path)
        try:
            resolved = path.resolve(strict=True)
        except OSError:
            return False
        try:
            valid = (
                not path.is_symlink()
                and resolved.parent == self._root
                and record.sha256 == entry.sha256
                and record.size_bytes == entry.size_bytes
                and resolved.stat().st_size == entry.size_bytes
                and self._sha256(resolved) == entry.sha256
                and self._health_check(entry, resolved)
            )
        except Exception:
            valid = False
        if not valid:
            return False
        self._installed[entry.model_id] = resolved
        self._active[entry.model_id] = resolved
        return True

    def mark_in_use(self, model_id: str, in_use: bool) -> None:
        if in_use:
            self._in_use[model_id] = self._in_use.get(model_id, 0) + 1
        else:
            remaining = self._in_use.get(model_id, 0) - 1
            if remaining > 0:
                self._in_use[model_id] = remaining
            else:
                self._in_use.pop(model_id, None)

    def deactivate(self, model_id: str) -> None:
        self._active.pop(model_id, None)

    def download(
        self,
        command: DownloadCommand,
        *,
        cancelled: Callable[[], bool] = lambda: False,
        progress: Callable[[int, int], None] | None = None,
    ) -> ModelOutcome:
        entry = command.entry
        if self._allowed.get(entry.model_id) != entry:
            return self._reject(entry, "NOT_ALLOWLISTED", "model is not in the trusted manifest")
        if entry.model_id in self._in_use:
            return self._reject(
                entry, "MODEL_IN_USE", "model cannot be updated while translation is using it"
            )
        if entry.bundled:
            return self._reject(entry, "BUNDLED_MODEL", "bundled models are not downloadable")
        if entry.size_bytes > _MAX_MODEL_BYTES:
            return self._reject(entry, "MODEL_TOO_LARGE", "model exceeds the supported size")
        source_url = str(entry.source_url)
        if not source_url.startswith("https://"):
            return self._reject(entry, "UNSAFE_URL", "model URL must use HTTPS")

        self._root.mkdir(parents=True, exist_ok=True)
        self._downloads.mkdir(parents=True, exist_ok=True)
        target = self._safe_path(self._root, f"{entry.model_id}.bin")
        partial = self._safe_path(self._downloads, f"{entry.model_id}.part")
        if os.path.lexists(partial):
            if not self._is_safe_regular_file(partial):
                return self._reject(
                    entry, "UNSAFE_PARTIAL", "model resume file failed safety validation"
                )
            if not command.allow_resume:
                partial.unlink()
        required = entry.size_bytes + min(entry.size_bytes, 64 * 1024 * 1024)
        if self._disk_free(self._root) < required:
            return self._reject(entry, "INSUFFICIENT_DISK", "not enough disk space for model")

        attempts = 0
        resumed = False
        while attempts < command.max_attempts:
            attempts += 1
            if cancelled():
                return self._cancel(entry, partial, attempts, resumed)
            offset = partial.stat().st_size if command.allow_resume and partial.exists() else 0
            if offset > entry.size_bytes:
                partial.unlink(missing_ok=True)
                offset = 0
            response: DownloadResponse | None = None
            try:
                response = self._source.open(source_url, offset=offset)
                if response.final_url != source_url:
                    partial.unlink(missing_ok=True)
                    return self._reject(entry, "URL_CHANGED", "redirected model URL was rejected")
                if offset and not response.supports_resume:
                    partial.unlink(missing_ok=True)
                    offset = 0
                    response.close()
                    response = self._source.open(source_url, offset=0)
                    if response.final_url != source_url:
                        return self._reject(
                            entry, "URL_CHANGED", "redirected model URL was rejected"
                        )
                if response.total_size is not None and response.total_size != entry.size_bytes:
                    partial.unlink(missing_ok=True)
                    return self._reject(entry, "SIZE_MISMATCH", "model size did not match manifest")
                resumed = resumed or offset > 0
                received = offset
                with self._open_partial(partial, resume=partial.exists()) as handle:
                    for chunk in response.chunks(_COPY_CHUNK_BYTES):
                        if cancelled():
                            handle.flush()
                            os.fsync(handle.fileno())
                            return self._cancel(entry, partial, attempts, resumed)
                        if not chunk:
                            continue
                        received += len(chunk)
                        if received > entry.size_bytes:
                            raise ValueError("download exceeded manifest size")
                        handle.write(chunk)
                        if progress is not None:
                            progress(received, entry.size_bytes)
                    handle.flush()
                    os.fsync(handle.fileno())
                if received != entry.size_bytes:
                    if attempts < command.max_attempts:
                        continue
                    partial.unlink(missing_ok=True)
                    return ModelOutcome(
                        ModelOutcomeStatus.FAILED,
                        entry.model_id,
                        "TRUNCATED",
                        "model download was incomplete",
                        bytes_received=received,
                        attempts=attempts,
                        resumed=resumed,
                    )
                digest = self._sha256(partial)
                if digest != entry.sha256:
                    partial.unlink(missing_ok=True)
                    return ModelOutcome(
                        ModelOutcomeStatus.FAILED,
                        entry.model_id,
                        "DIGEST_MISMATCH",
                        "model checksum did not match manifest",
                        bytes_received=received,
                        attempts=attempts,
                        resumed=resumed,
                    )
                if not self._health_check(entry, partial):
                    partial.unlink(missing_ok=True)
                    return ModelOutcome(
                        ModelOutcomeStatus.FAILED,
                        entry.model_id,
                        "HEALTH_CHECK_FAILED",
                        "downloaded model failed its health check",
                        bytes_received=received,
                        attempts=attempts,
                        resumed=resumed,
                    )
                self._activate(entry, partial, target)
                self._installed[entry.model_id] = target
                self._active[entry.model_id] = target
                return ModelOutcome(
                    ModelOutcomeStatus.ACTIVATED,
                    entry.model_id,
                    "ACTIVATED",
                    "model downloaded, verified, and activated",
                    target,
                    received,
                    attempts,
                    resumed,
                )
            except Exception:
                if attempts >= command.max_attempts:
                    return ModelOutcome(
                        ModelOutcomeStatus.FAILED,
                        entry.model_id,
                        "DOWNLOAD_FAILED",
                        "model download failed",
                        bytes_received=partial.stat().st_size if partial.exists() else 0,
                        attempts=attempts,
                        resumed=resumed,
                    )
            finally:
                if response is not None:
                    response.close()
        raise AssertionError("bounded download loop exhausted unexpectedly")

    def _activate(self, entry: ModelEntry, partial: Path, target: Path) -> None:
        backup = self._safe_path(self._downloads, f"{entry.model_id}.last-known-good")
        had_previous = target.exists()
        if had_previous:
            with suppress(OSError):
                backup.unlink(missing_ok=True)
            self._replace(target, backup)
        try:
            self._replace(partial, target)
            if self._store is not None:
                self._store.set_active(
                    InstalledModelRecord(
                        model_id=entry.model_id,
                        provider=entry.provider,
                        path=str(target),
                        sha256=entry.sha256,
                        size_bytes=entry.size_bytes,
                        license_id=entry.license_id,
                        active=True,
                        health_state="ready",
                    )
                )
        except Exception:
            if had_previous and backup.exists():
                self._replace(backup, target)
            else:
                target.unlink(missing_ok=True)
            raise
        if had_previous:
            with suppress(OSError):
                backup.unlink(missing_ok=True)

    def remove(self, model_id: str) -> ModelOutcome:
        path = self._installed.get(model_id)
        if path is None:
            return ModelOutcome(
                ModelOutcomeStatus.REJECTED,
                model_id,
                "NOT_INSTALLED",
                "model is not installed",
            )
        if model_id in self._active:
            return ModelOutcome(
                ModelOutcomeStatus.REJECTED,
                model_id,
                "MODEL_ACTIVE",
                "active model must be deactivated before removal",
                path,
            )
        if model_id in self._in_use:
            return ModelOutcome(
                ModelOutcomeStatus.REJECTED,
                model_id,
                "MODEL_IN_USE",
                "active model cannot be removed while in use",
                path,
            )
        try:
            path.unlink()
        except OSError:
            return ModelOutcome(
                ModelOutcomeStatus.FAILED,
                model_id,
                "REMOVE_FAILED",
                "model could not be removed",
                path,
            )
        self._installed.pop(model_id, None)
        if self._store is not None:
            try:
                self._store.delete(model_id)
            except OSError:
                return ModelOutcome(
                    ModelOutcomeStatus.FAILED,
                    model_id,
                    "STATE_DELETE_FAILED",
                    "model was removed but its local state could not be updated",
                )
        return ModelOutcome(ModelOutcomeStatus.REMOVED, model_id, "REMOVED", "model removed")

    @staticmethod
    def _safe_path(root: Path, filename: str) -> Path:
        candidate = root / filename
        resolved_parent = candidate.parent.resolve()
        if resolved_parent != root.resolve() or candidate.name != filename:
            raise ValueError("model path escapes managed storage")
        return candidate

    @staticmethod
    def _is_safe_regular_file(path: Path) -> bool:
        try:
            details = os.lstat(path)
        except OSError:
            return False
        reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        attributes = getattr(details, "st_file_attributes", 0)
        return (
            stat.S_ISREG(details.st_mode)
            and details.st_nlink == 1
            and not path.is_symlink()
            and not bool(attributes & reparse)
        )

    @classmethod
    def _open_partial(cls, path: Path, *, resume: bool) -> BinaryIO:
        flags = os.O_WRONLY | getattr(os, "O_BINARY", 0)
        flags |= os.O_APPEND if resume else os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags, 0o600)
        try:
            opened = os.fstat(descriptor)
            named = os.lstat(path)
            if (
                not cls._is_safe_regular_file(path)
                or opened.st_dev != named.st_dev
                or opened.st_ino != named.st_ino
            ):
                raise OSError("unsafe model partial file")
            return os.fdopen(descriptor, "ab" if resume else "wb")
        except Exception:
            os.close(descriptor)
            raise

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(_COPY_CHUNK_BYTES), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _reject(entry: ModelEntry, code: str, message: str) -> ModelOutcome:
        return ModelOutcome(ModelOutcomeStatus.REJECTED, entry.model_id, code, message)

    @staticmethod
    def _cancel(entry: ModelEntry, partial: Path, attempts: int, resumed: bool) -> ModelOutcome:
        return ModelOutcome(
            ModelOutcomeStatus.CANCELLED,
            entry.model_id,
            "CANCELLED",
            "model download was cancelled; partial resume data was retained",
            bytes_received=partial.stat().st_size if partial.exists() else 0,
            attempts=attempts,
            resumed=resumed,
        )
