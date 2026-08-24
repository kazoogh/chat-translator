from __future__ import annotations

import hashlib
import os
import shutil
import stat
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from threading import Lock

from game_chat_translator.model_management import ModelSource, UrllibModelSource

STT_MODEL_ID = "faster-whisper-small.en-local"
STT_MODEL_REVISION = "d1d751a5f8271d482d14ca55d9e2deeebbae577f"
_BUNDLE_NAME = "faster-whisper-small.en-d1d751a5"
_CHUNK_BYTES = 1024 * 1024
_DISK_RESERVE_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class SttModelFile:
    filename: str
    size_bytes: int
    sha256: str

    @property
    def url(self) -> str:
        return (
            "https://huggingface.co/Systran/faster-whisper-small.en/resolve/"
            f"{STT_MODEL_REVISION}/{self.filename}?download=true"
        )


STT_MODEL_FILES = (
    SttModelFile(
        "config.json",
        2_657,
        "666a9605530ac1f61fa8177f3702b4dacec9966749e42610839fcc32661d5fae",
    ),
    SttModelFile(
        "model.bin",
        483_545_366,
        "62b2a45b05ee59acb4a5341b33ee35e041395d378d418a18acfe4c9e768ee37a",
    ),
    SttModelFile(
        "tokenizer.json",
        2_128_466,
        "929c5252409436dce1b38a75d1abbcb5e132d170d8e324e4e04ed915fa2d22df",
    ),
    SttModelFile(
        "vocabulary.txt",
        422_309,
        "ff77588746d3a2595d32ab5b69ffd7b95ce2441ac57533cb66fc3eb575a115cf",
    ),
)


class SttSetupStatus(StrEnum):
    READY = "ready"
    INSTALLED = "installed"
    CANCELLED = "cancelled"
    FAILED = "failed"
    REJECTED = "rejected"
    REMOVED = "removed"


@dataclass(frozen=True, slots=True)
class SttSetupOutcome:
    status: SttSetupStatus
    code: str
    message: str


class SttModelSetup:
    """Install one immutable, checksum-verified local faster-whisper bundle."""

    def __init__(
        self,
        root: Path,
        source: ModelSource | None = None,
        *,
        files: tuple[SttModelFile, ...] = STT_MODEL_FILES,
        disk_free: Callable[[Path], int] | None = None,
        health_check: Callable[[Path], bool] | None = None,
        replace: Callable[[Path, Path], None] = os.replace,
    ) -> None:
        if not files or len({item.filename for item in files}) != len(files):
            raise ValueError("STT model manifest must contain unique files")
        if any(Path(item.filename).name != item.filename for item in files):
            raise ValueError("STT model filenames must be flat and contained")
        self._root = root.absolute()
        self._source = source or UrllibModelSource(timeout_seconds=45)
        self._files = files
        self._disk_free = disk_free or (lambda path: shutil.disk_usage(path).free)
        self._health_check = health_check or _local_health_check
        self._replace = replace
        self._operation_lock = Lock()

    @property
    def size_bytes(self) -> int:
        return sum(item.size_bytes for item in self._files)

    def ready_path(self) -> Path | None:
        bundle = self._root / _BUNDLE_NAME
        return bundle if self._valid_bundle(bundle) else None

    def install(
        self,
        *,
        cancelled: Callable[[], bool] = lambda: False,
        progress: Callable[[int, int], None] | None = None,
    ) -> SttSetupOutcome:
        if not self._operation_lock.acquire(blocking=False):
            return self._outcome(SttSetupStatus.REJECTED, "OPERATION_IN_PROGRESS")
        try:
            return self._install(cancelled, progress)
        finally:
            self._operation_lock.release()

    def remove(self, *, in_use: bool) -> SttSetupOutcome:
        if not self._operation_lock.acquire(blocking=False):
            return self._outcome(SttSetupStatus.REJECTED, "OPERATION_IN_PROGRESS")
        try:
            if in_use:
                return self._outcome(SttSetupStatus.REJECTED, "MODEL_IN_USE")
            target = self._root / _BUNDLE_NAME
            if not target.exists():
                return self._outcome(SttSetupStatus.REJECTED, "NOT_INSTALLED")
            if not self._safe_directory(target, expected_parent=self._root):
                return self._outcome(SttSetupStatus.FAILED, "UNSAFE_MODEL_PATH")
            shutil.rmtree(target)
            return self._outcome(SttSetupStatus.REMOVED, "REMOVED")
        except OSError:
            return self._outcome(SttSetupStatus.FAILED, "REMOVE_FAILED")
        finally:
            self._operation_lock.release()

    def _install(
        self,
        cancelled: Callable[[], bool],
        progress: Callable[[int, int], None] | None,
    ) -> SttSetupOutcome:
        if self.ready_path() is not None:
            return self._outcome(SttSetupStatus.READY, "ALREADY_READY")
        staging = Path()
        try:
            self._prepare_root()
            required = self.size_bytes * 2 + _DISK_RESERVE_BYTES
            if self._disk_free(self._root) < required:
                return self._outcome(SttSetupStatus.REJECTED, "INSUFFICIENT_DISK")
            staging = Path(tempfile.mkdtemp(prefix=".stt-staging-", dir=self._root))
            received = 0
            for item in self._files:
                if cancelled():
                    return self._outcome(SttSetupStatus.CANCELLED, "CANCELLED")
                destination = staging / item.filename
                response = self._source.open(item.url, offset=0)
                try:
                    if response.final_url != item.url or response.total_size != item.size_bytes:
                        return self._outcome(SttSetupStatus.FAILED, "MANIFEST_MISMATCH")
                    digest = hashlib.sha256()
                    written = 0
                    with self._exclusive_file(destination) as handle:
                        for chunk in response.chunks(_CHUNK_BYTES):
                            if cancelled():
                                return self._outcome(SttSetupStatus.CANCELLED, "CANCELLED")
                            if not chunk:
                                continue
                            written += len(chunk)
                            received += len(chunk)
                            if written > item.size_bytes:
                                return self._outcome(SttSetupStatus.FAILED, "SIZE_MISMATCH")
                            digest.update(chunk)
                            handle.write(chunk)
                            if progress is not None:
                                progress(received, self.size_bytes)
                        handle.flush()
                        os.fsync(handle.fileno())
                    if written != item.size_bytes or digest.hexdigest() != item.sha256:
                        return self._outcome(SttSetupStatus.FAILED, "DIGEST_MISMATCH")
                finally:
                    response.close()
            if not self._valid_bundle(staging) or not self._health_check(staging):
                return self._outcome(SttSetupStatus.FAILED, "HEALTH_CHECK_FAILED")
            self._activate(staging)
            staging = Path()
            return self._outcome(SttSetupStatus.INSTALLED, "INSTALLED")
        except (OSError, RuntimeError, ValueError):
            return self._outcome(SttSetupStatus.FAILED, "SETUP_FAILED")
        finally:
            if staging != Path() and self._contained_staging(staging):
                shutil.rmtree(staging, ignore_errors=True)

    def _prepare_root(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        if not self._safe_directory(self._root):
            raise OSError("unsafe STT model root")

    def _activate(self, staging: Path) -> None:
        target = self._root / _BUNDLE_NAME
        backup = self._root / f".{_BUNDLE_NAME}.last-known-good"
        if backup.exists():
            if not self._safe_directory(backup, expected_parent=self._root):
                raise OSError("unsafe STT backup path")
            shutil.rmtree(backup)
        had_target = target.exists()
        if had_target:
            if not self._safe_directory(target, expected_parent=self._root):
                raise OSError("unsafe STT target path")
            self._replace(target, backup)
        try:
            self._replace(staging, target)
        except Exception:
            if had_target and backup.exists() and not target.exists():
                self._replace(backup, target)
            raise
        if backup.exists():
            shutil.rmtree(backup)

    def _valid_bundle(self, bundle: Path) -> bool:
        try:
            if not self._safe_directory(bundle, expected_parent=self._root):
                return False
            actual = {path.name for path in bundle.iterdir() if path.is_file()}
            if actual != {item.filename for item in self._files}:
                return False
            return all(self._valid_file(bundle / item.filename, item) for item in self._files)
        except OSError:
            return False

    @staticmethod
    def _safe_directory(path: Path, *, expected_parent: Path | None = None) -> bool:
        details = os.lstat(path)
        attributes = getattr(details, "st_file_attributes", 0)
        reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        if not stat.S_ISDIR(details.st_mode) or path.is_symlink() or bool(attributes & reparse):
            return False
        return expected_parent is None or path.resolve().parent == expected_parent.resolve()

    @staticmethod
    def _valid_file(path: Path, item: SttModelFile) -> bool:
        details = os.lstat(path)
        attributes = getattr(details, "st_file_attributes", 0)
        reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_nlink != 1
            or path.is_symlink()
            or bool(attributes & reparse)
            or details.st_size != item.size_bytes
        ):
            return False
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(_CHUNK_BYTES):
                digest.update(chunk)
        return digest.hexdigest() == item.sha256

    def _contained_staging(self, staging: Path) -> bool:
        try:
            return (
                staging.parent.resolve() == self._root.resolve()
                and staging.name.startswith(".stt-staging-")
                and self._safe_directory(staging, expected_parent=self._root)
            )
        except OSError:
            return False

    @staticmethod
    def _exclusive_file(path: Path):  # type: ignore[no-untyped-def]
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags, 0o600)
        return os.fdopen(descriptor, "wb")

    @staticmethod
    def _outcome(status: SttSetupStatus, code: str) -> SttSetupOutcome:
        messages = {
            "ALREADY_READY": "Local speech recognition model is ready",
            "OPERATION_IN_PROGRESS": "Another speech model operation is already running",
            "INSUFFICIENT_DISK": "Not enough disk space for verified speech model setup",
            "CANCELLED": "Speech model setup was cancelled",
            "INSTALLED": "Speech model was downloaded, verified, and activated",
            "MODEL_IN_USE": "Stop speech recognition before removing its active model",
            "NOT_INSTALLED": "Speech model is not installed",
            "REMOVED": "Speech model removed",
            "UNSAFE_MODEL_PATH": "Speech model path failed safety validation",
            "REMOVE_FAILED": "Speech model could not be removed",
            "MANIFEST_MISMATCH": "Speech model source did not match its manifest",
            "SIZE_MISMATCH": "Speech model file exceeded its manifest size",
            "DIGEST_MISMATCH": "Speech model checksum did not match its manifest",
            "HEALTH_CHECK_FAILED": "Speech model failed its local health check",
            "SETUP_FAILED": "Speech model setup failed safely",
        }
        return SttSetupOutcome(status, code, messages[code])


def _local_health_check(path: Path) -> bool:
    from game_chat_translator.reply.faster_whisper_stt import IsolatedFasterWhisper

    service = IsolatedFasterWhisper(path)
    try:
        return service.health_check()
    finally:
        service.close()
