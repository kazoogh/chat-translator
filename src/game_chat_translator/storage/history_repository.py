from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from game_chat_translator.history import HistoryEntry, WindowGeometry
from game_chat_translator.storage.database import Database

_MAX_RETENTION_DAYS = 365
_MAX_ROW_LIMIT = 10_000
_MAX_LIST_LIMIT = 500


class HistoryRepository:
    """Explicit opt-in persistence. This class never logs message content."""

    def __init__(
        self,
        database: Database,
        *,
        maximum_rows: int = 1_000,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not 1 <= maximum_rows <= _MAX_ROW_LIMIT:
            raise ValueError("history row limit is outside its allowed bounds")
        self._database = database
        self._maximum_rows = maximum_rows
        self._now = now or (lambda: datetime.now(UTC))

    def append(
        self,
        entry: HistoryEntry,
        *,
        persistence_enabled: bool,
        retention_days: int,
    ) -> bool:
        """Persist only when the caller explicitly supplies an enabled privacy setting."""
        if not persistence_enabled:
            if retention_days != 0:
                raise ValueError("disabled history requires zero retention")
            return False
        if not 1 <= retention_days <= _MAX_RETENTION_DAYS:
            raise ValueError("enabled history retention must be between 1 and 365 days")
        now = self._aware_now()
        expires_at = now + timedelta(days=retention_days)
        payload = json.dumps(
            {
                "speaker": entry.speaker,
                "source_text": entry.source_text,
                "translated_text": entry.translated_text,
                "source_language": entry.source_language,
                "target_language": entry.target_language,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        with self._database.transaction() as connection:
            connection.execute(
                "DELETE FROM message_history WHERE expires_at <= ?", (now.isoformat(),)
            )
            connection.execute(
                """
                INSERT INTO message_history(
                    message_id, created_at, profile_id, payload_json, expires_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(message_id) DO UPDATE SET
                    created_at=excluded.created_at,
                    profile_id=excluded.profile_id,
                    payload_json=excluded.payload_json,
                    expires_at=excluded.expires_at
                """,
                (
                    entry.message_id,
                    entry.created_at_utc.isoformat(),
                    entry.profile_id,
                    payload,
                    expires_at.isoformat(),
                ),
            )
            connection.execute(
                """
                DELETE FROM message_history
                WHERE message_id IN (
                    SELECT message_id FROM message_history
                    ORDER BY created_at DESC, message_id DESC
                    LIMIT -1 OFFSET ?
                )
                """,
                (self._maximum_rows,),
            )
        return True

    def list_recent(self, *, limit: int = 100) -> tuple[HistoryEntry, ...]:
        if not 1 <= limit <= _MAX_LIST_LIMIT:
            raise ValueError("history list limit is outside its allowed bounds")
        now = self._aware_now()
        with self._database.transaction() as connection:
            connection.execute(
                "DELETE FROM message_history WHERE expires_at <= ?", (now.isoformat(),)
            )
            rows = connection.execute(
                """
                SELECT message_id, created_at, profile_id, payload_json
                FROM message_history
                ORDER BY created_at DESC, message_id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        entries: list[HistoryEntry] = []
        for row in rows:
            try:
                payload = json.loads(str(row["payload_json"]))
                entries.append(
                    HistoryEntry(
                        message_id=str(row["message_id"]),
                        created_at=datetime.fromisoformat(str(row["created_at"])),
                        profile_id=str(row["profile_id"]),
                        speaker=payload["speaker"],
                        source_text=payload["source_text"],
                        translated_text=payload["translated_text"],
                        source_language=payload["source_language"],
                        target_language=payload["target_language"],
                    )
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
        return tuple(entries)

    def purge_expired(self) -> int:
        with self._database.transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM message_history WHERE expires_at <= ?",
                (self._aware_now().isoformat(),),
            )
            return cursor.rowcount

    def clear(self) -> int:
        """Synchronously remove persisted history; other data classes are untouched."""
        with self._database.transaction() as connection:
            cursor = connection.execute("DELETE FROM message_history")
            return cursor.rowcount

    def save_geometry(self, geometry: WindowGeometry) -> None:
        with self._database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO window_geometry(display_id, x, y, width, height, maximized, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(display_id) DO UPDATE SET
                    x=excluded.x, y=excluded.y, width=excluded.width,
                    height=excluded.height, maximized=excluded.maximized,
                    updated_at=excluded.updated_at
                """,
                (
                    geometry.display_id,
                    geometry.x,
                    geometry.y,
                    geometry.width,
                    geometry.height,
                    int(geometry.maximized),
                    self._aware_now().isoformat(),
                ),
            )

    def load_geometry(self, display_id: str) -> WindowGeometry | None:
        if not display_id.strip() or len(display_id) > 200:
            raise ValueError("display ID is outside its allowed bounds")
        row = (
            self._database.open()
            .execute(
                "SELECT display_id, x, y, width, height, maximized FROM window_geometry "
                "WHERE display_id = ?",
                (display_id,),
            )
            .fetchone()
        )
        if row is None:
            return None
        return WindowGeometry(
            display_id=str(row["display_id"]),
            x=int(row["x"]),
            y=int(row["y"]),
            width=int(row["width"]),
            height=int(row["height"]),
            maximized=bool(row["maximized"]),
        )

    def load_latest_geometry(self) -> WindowGeometry | None:
        row = (
            self._database.open()
            .execute(
                "SELECT display_id, x, y, width, height, maximized FROM window_geometry "
                "ORDER BY updated_at DESC, display_id ASC LIMIT 1"
            )
            .fetchone()
        )
        if row is None:
            return None
        return WindowGeometry(
            display_id=str(row["display_id"]),
            x=int(row["x"]),
            y=int(row["y"]),
            width=int(row["width"]),
            height=int(row["height"]),
            maximized=bool(row["maximized"]),
        )

    def _aware_now(self) -> datetime:
        value = self._now()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("repository clock must be timezone-aware")
        return value.astimezone(UTC)
