from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from game_chat_translator.model_management import DownloadCommand, ModelLifecycleManager
from game_chat_translator.storage.database import Database
from game_chat_translator.storage.model_repository import SqliteModelStateStore
from game_chat_translator.validation.schemas import ModelEntry


@dataclass
class _Response:
    payload: bytes
    final_url: str
    total_size: int
    supports_resume: bool = True

    def chunks(self, _size: int):  # type: ignore[no-untyped-def]
        yield self.payload

    def close(self) -> None:
        pass


class _Source:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def open(self, url: str, *, offset: int) -> _Response:
        return _Response(self.payload[offset:], url, len(self.payload))


def _entry(payload: bytes) -> ModelEntry:
    return ModelEntry.model_validate(
        {
            "model_id": "context.test",
            "provider": "llama_cpp",
            "languages": ["ru", "tr", "en"],
            "hardware_tier": "cpu_low",
            "size_bytes": len(payload),
            "license_id": "Apache-2.0",
            "source_url": "https://models.example.invalid/context.gguf",
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    )


def test_verified_model_restores_from_sqlite_after_restart(tmp_path: Path) -> None:
    payload = b"healthy-model"
    entry = _entry(payload)
    database_path = tmp_path / "state.sqlite3"
    model_root = tmp_path / "models"
    with Database(database_path) as database:
        lifecycle = ModelLifecycleManager(
            model_root,
            _Source(payload),
            lambda _entry, path: path.read_bytes().startswith(b"healthy"),
            allowed_entries=(entry,),
            disk_free=lambda _path: 10**9,
            store=SqliteModelStateStore(database),
        )
        assert lifecycle.download(DownloadCommand(entry)).code == "ACTIVATED"

    with Database(database_path) as database:
        restored = ModelLifecycleManager(
            model_root,
            _Source(payload),
            lambda _entry, path: path.read_bytes().startswith(b"healthy"),
            allowed_entries=(entry,),
            store=SqliteModelStateStore(database),
        )
        assert restored.restore(entry)
        assert restored.active_path(entry.model_id) == model_root / "context.test.bin"


def test_tampered_persisted_model_never_restores(tmp_path: Path) -> None:
    payload = b"healthy-model"
    entry = _entry(payload)
    with Database(tmp_path / "state.sqlite3") as database:
        lifecycle = ModelLifecycleManager(
            tmp_path / "models",
            _Source(payload),
            lambda _entry, _path: True,
            allowed_entries=(entry,),
            disk_free=lambda _path: 10**9,
            store=SqliteModelStateStore(database),
        )
        outcome = lifecycle.download(DownloadCommand(entry))
        assert outcome.path is not None
        outcome.path.write_bytes(b"tampered-data")
        restarted = ModelLifecycleManager(
            tmp_path / "models",
            _Source(payload),
            lambda _entry, _path: True,
            allowed_entries=(entry,),
            store=SqliteModelStateStore(database),
        )
        assert not restarted.restore(entry)
