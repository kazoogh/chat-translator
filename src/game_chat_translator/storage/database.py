from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from threading import RLock

from game_chat_translator.settings import default_data_dir


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    sql: str
    digest: str


def bundled_migrations() -> tuple[Migration, ...]:
    root = files("game_chat_translator.storage.migrations")
    migrations: list[Migration] = []
    for resource in sorted(root.iterdir(), key=lambda item: item.name):
        if not resource.name.endswith(".sql"):
            continue
        prefix, _, label = resource.name.partition("_")
        sql = resource.read_text(encoding="utf-8")
        migrations.append(
            Migration(
                version=int(prefix),
                name=label.removesuffix(".sql"),
                sql=sql,
                digest=hashlib.sha256(sql.encode("utf-8")).hexdigest(),
            )
        )
    return tuple(migrations)


def _sql_statements(script: str) -> tuple[str, ...]:
    statements: list[str] = []
    pending = ""
    for line in script.splitlines(keepends=True):
        pending += line
        if sqlite3.complete_statement(pending):
            if pending.strip():
                statements.append(pending)
            pending = ""
    if pending.strip():
        raise MigrationError("migration ends with an incomplete SQL statement")
    return tuple(statements)


class Database:
    def __init__(self, path: Path | None = None, *, busy_timeout_ms: int = 5000) -> None:
        self.path = path or default_data_dir() / "state.sqlite3"
        self.busy_timeout_ms = busy_timeout_ms
        self._connection: sqlite3.Connection | None = None
        self._lock = RLock()

    def open(self) -> sqlite3.Connection:
        with self._lock:
            if self._connection is not None:
                return self._connection
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(
                self.path,
                isolation_level=None,
                check_same_thread=False,
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute(f"PRAGMA busy_timeout={int(self.busy_timeout_ms)}")
            self._connection = connection
            self.migrate()
            return connection

    def migrate(self) -> None:
        connection = self._require_connection()
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                digest TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )
        applied = {
            int(row["version"]): str(row["digest"])
            for row in connection.execute("SELECT version, digest FROM schema_migrations")
        }
        for migration in bundled_migrations():
            if migration.version in applied:
                if applied[migration.version] != migration.digest:
                    raise MigrationError(
                        f"Applied migration {migration.version} has changed; "
                        "restore a compatible build"
                    )
                continue
            try:
                with self.transaction() as transaction:
                    for statement in _sql_statements(migration.sql):
                        transaction.execute(statement)
                    transaction.execute(
                        "INSERT INTO schema_migrations(version, name, digest, applied_at) "
                        "VALUES (?, ?, ?, ?)",
                        (
                            migration.version,
                            migration.name,
                            migration.digest,
                            datetime.now(UTC).isoformat(),
                        ),
                    )
            except sqlite3.Error as exc:
                raise MigrationError(f"Migration {migration.version} failed") from exc

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            connection = self._require_connection()
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except BaseException:
                connection.execute("ROLLBACK")
                raise
            else:
                connection.execute("COMMIT")

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    def _require_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("database is not open")
        return self._connection

    def __enter__(self) -> Database:
        self.open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
