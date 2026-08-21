from __future__ import annotations

from pathlib import Path
from threading import Thread
from uuid import UUID

from game_chat_translator.models import ChatRegion
from game_chat_translator.storage.database import Database, bundled_migrations
from game_chat_translator.storage.repositories import SqliteStateRepository


def test_migrations_are_repeatable_and_enable_required_pragmas(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    with Database(path) as database:
        connection = database.open()
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        expected = len(bundled_migrations())
        count = connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
        assert count == expected
        database.migrate()
        count = connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
        assert count == expected


def test_calibration_repository_round_trip(tmp_path: Path) -> None:
    with Database(tmp_path / "state.sqlite3") as database:
        repository = SqliteStateRepository(database)
        assert not repository.has_calibration("stalzone.default")
        region = ChatRegion(
            x=0.01,
            y=0.75,
            width=0.45,
            height=0.2,
            layout_id="windowed",
            reference_client_width=2560,
            reference_client_height=1440,
            reference_dpi=120,
        )
        calibration_id = repository.save_calibration("stalzone.default", "monitor-1", region, 1.0)
        assert isinstance(calibration_id, UUID)
        assert repository.has_calibration("stalzone.default")
        assert repository.get_calibration(calibration_id) == region
        assert (
            repository.find_calibration(
                "stalzone.default", "windowed", "monitor-1", 3440, 1440, 144, 1.0
            )
            == region
        )


def test_transaction_rolls_back_on_error(tmp_path: Path) -> None:
    with Database(tmp_path / "state.sqlite3") as database:
        try:
            with database.transaction() as connection:
                connection.execute(
                    "INSERT INTO profile_overrides VALUES (?, ?, ?, ?)",
                    ("generic.default", 1, "{}", "now"),
                )
                raise RuntimeError("fail")
        except RuntimeError:
            pass
        assert database.open().execute("SELECT COUNT(*) FROM profile_overrides").fetchone()[0] == 0


def test_transactions_are_serialized_across_worker_threads(tmp_path: Path) -> None:
    with Database(tmp_path / "state.sqlite3") as database:
        failures: list[Exception] = []

        def write(index: int) -> None:
            try:
                with database.transaction() as connection:
                    connection.execute(
                        "INSERT INTO profile_overrides VALUES (?, ?, ?, ?)",
                        (f"profile-{index}", 1, "{}", "now"),
                    )
            except Exception as exc:
                failures.append(exc)

        workers = [Thread(target=write, args=(index,)) for index in range(8)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(2)
        assert failures == []
        assert database.open().execute("SELECT COUNT(*) FROM profile_overrides").fetchone()[0] == 8
