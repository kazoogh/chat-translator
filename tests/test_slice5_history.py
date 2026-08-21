from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from game_chat_translator.history import HistoryEntry, WindowGeometry
from game_chat_translator.storage.database import Database
from game_chat_translator.storage.history_repository import HistoryRepository

NOW = datetime(2026, 8, 21, 12, tzinfo=UTC)


def entry(index: int, *, created_at: datetime | None = None) -> HistoryEntry:
    return HistoryEntry(
        message_id=f"message-{index}",
        created_at=created_at or NOW + timedelta(seconds=index),
        profile_id="stalzone.default",
        speaker=f"Player{index}",
        source_text=f"private source {index}",
        translated_text=f"private translation {index}",
        source_language="ru",
    )


def repository(database: Database, *, maximum_rows: int = 3) -> HistoryRepository:
    return HistoryRepository(database, maximum_rows=maximum_rows, now=lambda: NOW)


def test_history_write_requires_explicit_opt_in_and_valid_retention(tmp_path: Path) -> None:
    with Database(tmp_path / "state.sqlite3") as database:
        history = repository(database)
        assert not history.append(entry(1), persistence_enabled=False, retention_days=0)
        assert database.open().execute("SELECT COUNT(*) FROM message_history").fetchone()[0] == 0
        with pytest.raises(ValueError, match="zero retention"):
            history.append(entry(1), persistence_enabled=False, retention_days=1)
        for days in (0, 366):
            with pytest.raises(ValueError, match="between 1 and 365"):
                history.append(entry(1), persistence_enabled=True, retention_days=days)


def test_history_is_bounded_and_recent_listing_is_bounded(tmp_path: Path) -> None:
    with Database(tmp_path / "state.sqlite3") as database:
        history = repository(database)
        for index in range(6):
            assert history.append(entry(index), persistence_enabled=True, retention_days=7)
        assert [item.message_id for item in history.list_recent(limit=2)] == [
            "message-5",
            "message-4",
        ]
        assert database.open().execute("SELECT COUNT(*) FROM message_history").fetchone()[0] == 3
        with pytest.raises(ValueError, match="list limit"):
            history.list_recent(limit=501)


def test_expiry_is_aware_purged_and_never_returned(tmp_path: Path) -> None:
    with Database(tmp_path / "state.sqlite3") as database:
        history = repository(database)
        history.append(entry(1), persistence_enabled=True, retention_days=1)
        database.open().execute(
            "UPDATE message_history SET expires_at = ? WHERE message_id = ?",
            ((NOW - timedelta(seconds=1)).isoformat(), "message-1"),
        )
        assert history.list_recent() == ()
        assert database.open().execute("SELECT COUNT(*) FROM message_history").fetchone()[0] == 0

        with pytest.raises(ValueError, match="timezone-aware"):
            HistoryEntry(
                message_id="naive",
                created_at=datetime(2026, 8, 21),
                profile_id="profile",
                speaker=None,
                source_text="source",
                translated_text="translation",
                source_language="ru",
            )


def test_clear_is_synchronous_and_does_not_touch_other_state(tmp_path: Path) -> None:
    with Database(tmp_path / "state.sqlite3") as database:
        history = repository(database)
        history.append(entry(1), persistence_enabled=True, retention_days=1)
        database.open().execute(
            """
            INSERT INTO profile_overrides(profile_id, schema_version, override_json, updated_at)
            VALUES ('test.profile', 1, '{}', ?)
            """,
            (NOW.isoformat(),),
        )
        assert history.clear() == 1
        assert history.list_recent() == ()
        assert database.open().execute("SELECT COUNT(*) FROM profile_overrides").fetchone()[0] == 1


def test_window_geometry_is_display_scoped_validated_and_persistent(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    primary = WindowGeometry("display-primary", 20, 30, 800, 500)
    secondary = WindowGeometry("display-secondary", -1200, 10, 1000, 700, maximized=True)
    with Database(path) as database:
        history = repository(database)
        history.save_geometry(primary)
        history.save_geometry(secondary)
        history.save_geometry(WindowGeometry("display-primary", 40, 50, 900, 600))
    with Database(path) as database:
        history = repository(database)
        assert history.load_geometry("display-primary") == WindowGeometry(
            "display-primary", 40, 50, 900, 600
        )
        assert history.load_geometry("display-secondary") == secondary
        assert history.load_geometry("unknown") is None
        with pytest.raises(ValueError, match="window size"):
            WindowGeometry("display", 0, 0, 20, 20)


def test_malformed_payload_is_not_exposed_or_logged(tmp_path: Path) -> None:
    with Database(tmp_path / "state.sqlite3") as database:
        database.open().execute(
            """
            INSERT INTO message_history(
                message_id, created_at, profile_id, payload_json, expires_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            ("bad", NOW.isoformat(), "profile", "not-json", (NOW + timedelta(days=1)).isoformat()),
        )
        assert repository(database).list_recent() == ()
