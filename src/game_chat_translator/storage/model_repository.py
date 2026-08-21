from __future__ import annotations

from datetime import UTC, datetime

from game_chat_translator.model_management.lifecycle import InstalledModelRecord, ModelStateStore
from game_chat_translator.storage.database import Database


class SqliteModelStateStore(ModelStateStore):
    def __init__(self, database: Database) -> None:
        self._database = database

    def get(self, model_id: str) -> InstalledModelRecord | None:
        row = (
            self._database.open()
            .execute("SELECT * FROM installed_models WHERE model_id = ?", (model_id,))
            .fetchone()
        )
        if row is None:
            return None
        return InstalledModelRecord(
            model_id=str(row["model_id"]),
            provider=str(row["provider"]),
            path=str(row["path"]),
            sha256=str(row["sha256"]),
            size_bytes=int(row["size_bytes"]),
            license_id=str(row["license_id"]),
            active=bool(row["active"]),
            health_state=str(row["health_state"]),
        )

    def set_active(self, record: InstalledModelRecord) -> None:
        now = datetime.now(UTC).isoformat()
        with self._database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO installed_models(
                    model_id, provider, path, sha256, license_id, health_state,
                    installed_at, last_checked_at, size_bytes, active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(model_id) DO UPDATE SET
                    provider=excluded.provider,
                    path=excluded.path,
                    sha256=excluded.sha256,
                    license_id=excluded.license_id,
                    health_state=excluded.health_state,
                    last_checked_at=excluded.last_checked_at,
                    size_bytes=excluded.size_bytes,
                    active=excluded.active
                """,
                (
                    record.model_id,
                    record.provider,
                    record.path,
                    record.sha256,
                    record.license_id,
                    record.health_state,
                    now,
                    now,
                    record.size_bytes,
                    int(record.active),
                ),
            )

    def delete(self, model_id: str) -> None:
        with self._database.transaction() as connection:
            connection.execute("DELETE FROM installed_models WHERE model_id = ?", (model_id,))
