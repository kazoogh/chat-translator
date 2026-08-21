from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from game_chat_translator.models import ChatRegion
from game_chat_translator.storage.database import Database


class StateRepository(Protocol):
    def save_calibration(
        self, profile_id: str, monitor_id: str, region: ChatRegion, game_ui_scale: float | None
    ) -> UUID: ...

    def get_calibration(self, calibration_id: UUID) -> ChatRegion | None: ...

    def find_calibration(
        self,
        profile_id: str,
        layout_id: str,
        monitor_id: str,
        client_width: int,
        client_height: int,
        dpi: int,
        game_ui_scale: float | None,
    ) -> ChatRegion | None: ...

    def clear_message_history(self) -> int: ...


class SqliteStateRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def save_calibration(
        self, profile_id: str, monitor_id: str, region: ChatRegion, game_ui_scale: float | None
    ) -> UUID:
        calibration_id = uuid4()
        now = datetime.now(UTC).isoformat()
        connection = self.database.open()
        with self.database.transaction():
            connection.execute(
                """
                INSERT INTO calibrations(
                    calibration_id, profile_id, layout_id, monitor_id,
                    client_width, client_height, dpi, game_ui_scale,
                    normalized_x, normalized_y, normalized_width, normalized_height,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(
                    profile_id, layout_id, monitor_id, client_width,
                    client_height, dpi, game_ui_scale
                )
                DO UPDATE SET normalized_x=excluded.normalized_x,
                              normalized_y=excluded.normalized_y,
                              normalized_width=excluded.normalized_width,
                              normalized_height=excluded.normalized_height,
                              updated_at=excluded.updated_at
                """,
                (
                    str(calibration_id),
                    profile_id,
                    region.layout_id,
                    monitor_id,
                    region.reference_client_width,
                    region.reference_client_height,
                    region.reference_dpi,
                    game_ui_scale,
                    region.x,
                    region.y,
                    region.width,
                    region.height,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                """
                SELECT calibration_id FROM calibrations
                WHERE profile_id = ? AND layout_id = ? AND monitor_id = ?
                  AND client_width = ? AND client_height = ? AND dpi = ?
                  AND (game_ui_scale = ? OR (game_ui_scale IS NULL AND ? IS NULL))
                """,
                (
                    profile_id,
                    region.layout_id,
                    monitor_id,
                    region.reference_client_width,
                    region.reference_client_height,
                    region.reference_dpi,
                    game_ui_scale,
                    game_ui_scale,
                ),
            ).fetchone()
        return UUID(row["calibration_id"])

    def get_calibration(self, calibration_id: UUID) -> ChatRegion | None:
        row = (
            self.database.open()
            .execute("SELECT * FROM calibrations WHERE calibration_id = ?", (str(calibration_id),))
            .fetchone()
        )
        if row is None:
            return None
        return ChatRegion(
            x=row["normalized_x"],
            y=row["normalized_y"],
            width=row["normalized_width"],
            height=row["normalized_height"],
            layout_id=row["layout_id"],
            reference_client_width=row["client_width"],
            reference_client_height=row["client_height"],
            reference_dpi=row["dpi"],
        )

    def find_calibration(
        self,
        profile_id: str,
        layout_id: str,
        monitor_id: str,
        client_width: int,
        client_height: int,
        dpi: int,
        game_ui_scale: float | None,
    ) -> ChatRegion | None:
        row = (
            self.database.open()
            .execute(
                """
            SELECT * FROM calibrations
            WHERE profile_id = ? AND layout_id = ? AND monitor_id = ?
              AND (game_ui_scale = ? OR (game_ui_scale IS NULL AND ? IS NULL))
            ORDER BY
              CASE WHEN client_width = ? AND client_height = ? AND dpi = ? THEN 0 ELSE 1 END,
              ABS(client_width - ?) + ABS(client_height - ?) + ABS(dpi - ?),
              updated_at DESC
            LIMIT 1
            """,
                (
                    profile_id,
                    layout_id,
                    monitor_id,
                    game_ui_scale,
                    game_ui_scale,
                    client_width,
                    client_height,
                    dpi,
                    client_width,
                    client_height,
                    dpi,
                ),
            )
            .fetchone()
        )
        if row is None:
            return None
        return ChatRegion(
            x=row["normalized_x"],
            y=row["normalized_y"],
            width=row["normalized_width"],
            height=row["normalized_height"],
            layout_id=row["layout_id"],
            reference_client_width=row["client_width"],
            reference_client_height=row["client_height"],
            reference_dpi=row["dpi"],
        )

    def save_profile_override(self, profile_id: str, schema_version: int, payload: object) -> None:
        now = datetime.now(UTC).isoformat()
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO profile_overrides(profile_id, schema_version, override_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(profile_id) DO UPDATE SET
                    schema_version=excluded.schema_version,
                    override_json=excluded.override_json,
                    updated_at=excluded.updated_at
                """,
                (profile_id, schema_version, encoded, now),
            )

    def clear_message_history(self) -> int:
        with self.database.transaction() as connection:
            cursor = connection.execute("DELETE FROM message_history")
            return cursor.rowcount
