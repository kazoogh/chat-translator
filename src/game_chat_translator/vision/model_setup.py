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

OCR_MODEL_ID = "paddleocr-v5-cyrillic-local"
_BUNDLE_NAME = "paddleocr-v5-cyrillic-pinned-v1"
_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True, slots=True)
class OcrModelFile:
    component: str
    filename: str
    url: str
    size_bytes: int
    sha256: str


OCR_MODEL_FILES = (
    OcrModelFile(
        "PP-OCRv5_mobile_det_infer",
        "config.json",
        "https://huggingface.co/PaddlePaddle/PP-OCRv5_mobile_det/resolve/0d63e78e2b680928f6b1747d76a08db6e645efb7/config.json?download=true",
        2871,
        "7ac1c33f377ba58561f4b89d3180b6add2b7c5c60a4edac90fa4e0ceccdc6665",
    ),
    OcrModelFile(
        "PP-OCRv5_mobile_det_infer",
        "inference.json",
        "https://huggingface.co/PaddlePaddle/PP-OCRv5_mobile_det/resolve/0d63e78e2b680928f6b1747d76a08db6e645efb7/inference.json?download=true",
        229777,
        "05feef1acb00aa4cd7362b15f7f501fc4f99d7b1fa73c1c871e0c7b1504b0f5c",
    ),
    OcrModelFile(
        "PP-OCRv5_mobile_det_infer",
        "inference.pdiparams",
        "https://huggingface.co/PaddlePaddle/PP-OCRv5_mobile_det/resolve/0d63e78e2b680928f6b1747d76a08db6e645efb7/inference.pdiparams?download=true",
        4692937,
        "afa1820cb16c1fd0dad589d0f8b389139061c1ef6d68019685fd07be997dda5b",
    ),
    OcrModelFile(
        "PP-OCRv5_mobile_det_infer",
        "inference.yml",
        "https://huggingface.co/PaddlePaddle/PP-OCRv5_mobile_det/resolve/0d63e78e2b680928f6b1747d76a08db6e645efb7/inference.yml?download=true",
        903,
        "98069072e1b6b37d727fd9d9f11725faa46d6ea0de012f2ed26caea011c37699",
    ),
    OcrModelFile(
        "cyrillic_PP-OCRv5_mobile_rec_infer",
        "config.json",
        "https://huggingface.co/PaddlePaddle/cyrillic_PP-OCRv5_mobile_rec/resolve/712d2d65556ccc1ea7b5d2bb232b018838b6a3ab/config.json?download=true",
        18036,
        "b62d0464a75de5c367adbc13bf392a99074bf8c97f3429c4888447345528efee",
    ),
    OcrModelFile(
        "cyrillic_PP-OCRv5_mobile_rec_infer",
        "inference.json",
        "https://huggingface.co/PaddlePaddle/cyrillic_PP-OCRv5_mobile_rec/resolve/712d2d65556ccc1ea7b5d2bb232b018838b6a3ab/inference.json?download=true",
        217712,
        "5d90f1bfca52d80c01de176c5238fae2459995a99ff1dbfe5319ab4ed1735df2",
    ),
    OcrModelFile(
        "cyrillic_PP-OCRv5_mobile_rec_infer",
        "inference.pdiparams",
        "https://huggingface.co/PaddlePaddle/cyrillic_PP-OCRv5_mobile_rec/resolve/712d2d65556ccc1ea7b5d2bb232b018838b6a3ab/inference.pdiparams?download=true",
        7972691,
        "434dc9fa2a99fa3653e08f8cf793ae56be7dd41c35c4980e6255147cc02bbc80",
    ),
    OcrModelFile(
        "cyrillic_PP-OCRv5_mobile_rec_infer",
        "inference.yml",
        "https://huggingface.co/PaddlePaddle/cyrillic_PP-OCRv5_mobile_rec/resolve/712d2d65556ccc1ea7b5d2bb232b018838b6a3ab/inference.yml?download=true",
        6991,
        "5c76cc91fa98410178a09f498db10050d0ec1634a660053d3005ab7be581f501",
    ),
)


class OcrSetupStatus(StrEnum):
    READY = "ready"
    INSTALLED = "installed"
    CANCELLED = "cancelled"
    FAILED = "failed"
    REMOVED = "removed"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class OcrSetupOutcome:
    status: OcrSetupStatus
    code: str
    message: str


class OcrModelSetup:
    """Explicit, revision-pinned and checksum-verified PaddleOCR model setup."""

    def __init__(
        self,
        root: Path,
        source: ModelSource | None = None,
        *,
        disk_free: Callable[[Path], int] | None = None,
    ) -> None:
        self._root = root
        self._source = source or UrllibModelSource(timeout_seconds=45)
        self._disk_free = disk_free or (lambda path: shutil.disk_usage(path).free)
        self._operation_lock = Lock()

    @property
    def size_bytes(self) -> int:
        return sum(item.size_bytes for item in OCR_MODEL_FILES)

    def ready_paths(self) -> tuple[Path, Path] | None:
        bundle = self._root / _BUNDLE_NAME
        if not self._valid_bundle(bundle):
            return None
        return (
            bundle / "PP-OCRv5_mobile_det_infer",
            bundle / "cyrillic_PP-OCRv5_mobile_rec_infer",
        )

    def install(
        self,
        *,
        cancelled: Callable[[], bool] = lambda: False,
        progress: Callable[[int, int], None] | None = None,
    ) -> OcrSetupOutcome:
        if not self._operation_lock.acquire(blocking=False):
            return OcrSetupOutcome(
                OcrSetupStatus.REJECTED,
                "OPERATION_IN_PROGRESS",
                "Another OCR model operation is already running",
            )
        try:
            return self._install(cancelled=cancelled, progress=progress)
        finally:
            self._operation_lock.release()

    def _install(
        self,
        *,
        cancelled: Callable[[], bool],
        progress: Callable[[int, int], None] | None,
    ) -> OcrSetupOutcome:
        if self.ready_paths() is not None:
            return OcrSetupOutcome(OcrSetupStatus.READY, "ALREADY_READY", "OCR models are ready")
        try:
            self._prepare_root()
            if self._disk_free(self._root) < self.size_bytes * 2 + 16 * 1024 * 1024:
                return OcrSetupOutcome(
                    OcrSetupStatus.REJECTED,
                    "INSUFFICIENT_DISK",
                    "Not enough disk space for verified OCR model setup",
                )
            staging = Path(tempfile.mkdtemp(prefix=".ocr-staging-", dir=self._root))
        except OSError:
            return self._failed("STAGING_FAILED", "OCR model storage could not be prepared")
        received = 0
        try:
            for item in OCR_MODEL_FILES:
                if cancelled():
                    return OcrSetupOutcome(
                        OcrSetupStatus.CANCELLED, "CANCELLED", "OCR model setup was cancelled"
                    )
                destination = staging / item.component / item.filename
                destination.parent.mkdir(parents=True, exist_ok=True)
                response = self._source.open(item.url, offset=0)
                try:
                    if response.final_url != item.url or response.total_size != item.size_bytes:
                        return self._failed(
                            "MANIFEST_MISMATCH", "OCR model source did not match its manifest"
                        )
                    digest = hashlib.sha256()
                    written = 0
                    with self._exclusive_file(destination) as handle:
                        for chunk in response.chunks(_CHUNK_BYTES):
                            if cancelled():
                                return OcrSetupOutcome(
                                    OcrSetupStatus.CANCELLED,
                                    "CANCELLED",
                                    "OCR model setup was cancelled",
                                )
                            if not chunk:
                                continue
                            written += len(chunk)
                            received += len(chunk)
                            if written > item.size_bytes:
                                return self._failed(
                                    "SIZE_MISMATCH", "OCR model file exceeded its manifest size"
                                )
                            digest.update(chunk)
                            handle.write(chunk)
                            if progress is not None:
                                progress(received, self.size_bytes)
                        handle.flush()
                        os.fsync(handle.fileno())
                    if written != item.size_bytes or digest.hexdigest() != item.sha256:
                        return self._failed(
                            "DIGEST_MISMATCH", "OCR model checksum did not match its manifest"
                        )
                finally:
                    response.close()
            if not self._valid_bundle(staging):
                return self._failed("HEALTH_CHECK_FAILED", "OCR model bundle was incomplete")
            self._activate(staging)
            staging = Path()
            return OcrSetupOutcome(
                OcrSetupStatus.INSTALLED,
                "INSTALLED",
                "OCR models were downloaded, verified, and activated",
            )
        except (OSError, RuntimeError, ValueError):
            return self._failed("DOWNLOAD_FAILED", "OCR model setup failed")
        finally:
            if staging != Path() and self._contained_staging(staging):
                shutil.rmtree(staging, ignore_errors=True)

    def remove(self, *, in_use: bool) -> OcrSetupOutcome:
        if not self._operation_lock.acquire(blocking=False):
            return OcrSetupOutcome(
                OcrSetupStatus.REJECTED,
                "OPERATION_IN_PROGRESS",
                "Another OCR model operation is already running",
            )
        try:
            return self._remove(in_use=in_use)
        finally:
            self._operation_lock.release()

    def _remove(self, *, in_use: bool) -> OcrSetupOutcome:
        if in_use:
            return OcrSetupOutcome(
                OcrSetupStatus.REJECTED,
                "MODEL_IN_USE",
                "Pause and restart before removing active OCR models",
            )
        target = self._root / _BUNDLE_NAME
        if not target.exists():
            return OcrSetupOutcome(
                OcrSetupStatus.REJECTED, "NOT_INSTALLED", "OCR models are not installed"
            )
        if target.is_symlink() or target.parent.resolve() != self._root.resolve():
            return self._failed("UNSAFE_MODEL_PATH", "OCR model path failed safety validation")
        try:
            shutil.rmtree(target)
        except OSError:
            return self._failed("REMOVE_FAILED", "OCR models could not be removed")
        return OcrSetupOutcome(OcrSetupStatus.REMOVED, "REMOVED", "OCR models removed")

    def _prepare_root(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        if self._root.is_symlink() or not self._root.is_dir():
            raise OSError("unsafe OCR model root")

    def _activate(self, staging: Path) -> None:
        target = self._root / _BUNDLE_NAME
        backup = self._root / f".{_BUNDLE_NAME}.last-known-good"
        if backup.exists():
            shutil.rmtree(backup)
        had_target = target.exists()
        if had_target:
            os.replace(target, backup)
        try:
            os.replace(staging, target)
        except Exception:
            if had_target and backup.exists():
                os.replace(backup, target)
            raise
        if backup.exists():
            shutil.rmtree(backup)

    def _valid_bundle(self, bundle: Path) -> bool:
        try:
            if bundle.is_symlink() or not bundle.is_dir():
                return False
            if bundle.resolve().parent != self._root.resolve():
                return False
            expected = {(item.component, item.filename) for item in OCR_MODEL_FILES}
            actual = {
                (path.parent.name, path.name) for path in bundle.glob("*/*") if path.is_file()
            }
            if actual != expected:
                return False
            return all(self._valid_file(bundle, item) for item in OCR_MODEL_FILES)
        except OSError:
            return False

    @staticmethod
    def _valid_file(bundle: Path, item: OcrModelFile) -> bool:
        path = bundle / item.component / item.filename
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
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return digest == item.sha256

    def _contained_staging(self, staging: Path) -> bool:
        try:
            return staging.parent.resolve() == self._root.resolve() and staging.name.startswith(
                ".ocr-staging-"
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
    def _failed(code: str, message: str) -> OcrSetupOutcome:
        return OcrSetupOutcome(OcrSetupStatus.FAILED, code, message)
