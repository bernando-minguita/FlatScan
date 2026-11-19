"""SQLite connection factory with schema migrations."""

from __future__ import annotations

import contextlib
import logging
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app import constants

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


class DatabaseError(Exception):
    """User-facing database failure."""


class Database:
    """Owns the database path and applies schema migrations once."""

    def __init__(self, path: Path | str | None = None) -> None:
        # Read lazily so a read-only-install relocation (config._relocate_storage)
        # is honoured even when no explicit path is passed.
        self.path = Path(path) if path else constants.DATABASE_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialized = False

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        try:
            connection = sqlite3.connect(str(self.path), timeout=15.0)
        except sqlite3.Error as exc:
            raise DatabaseError(f"Could not open the local database: {exc}") from exc
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = WAL")
            yield connection
            connection.commit()
        except sqlite3.Error as exc:
            connection.rollback()
            raise DatabaseError(f"Database operation failed: {exc}") from exc
        finally:
            connection.close()

    # ----------------------------------------------------------- migrations
    def initialize(self) -> None:
        with self._lock:
            if self._initialized:
                return
            with self.connect() as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                        version TEXT PRIMARY KEY,
                        applied_at TEXT NOT NULL
                    )
                    """
                )
                applied = {
                    row["version"]
                    for row in connection.execute("SELECT version FROM schema_migrations")
                }
                for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
                    version = migration.stem
                    if version in applied:
                        continue
                    logger.info("Applying migration %s", version)
                    sql = migration.read_text(encoding="utf-8")
                    try:
                        # Run the whole script inside one explicit transaction
                        # (executescript commits any pending implicit
                        # transaction before running the script; the BEGIN
                        # below keeps every statement atomic until the record
                        # insert and the commit that follow).
                        connection.executescript("BEGIN IMMEDIATE;\n" + sql)
                        connection.execute(
                            "INSERT OR REPLACE INTO schema_migrations(version, applied_at) "
                            "VALUES (?, datetime('now'))",
                            (version,),
                        )
                        connection.commit()
                    except sqlite3.Error as exc:
                        # Roll back the entire migration: a partially applied
                        # schema must never be recorded as migrated (or left
                        # behind unrecorded).
                        try:
                            connection.execute("ROLLBACK")
                        except sqlite3.Error:
                            pass
                        raise DatabaseError(
                            f"Migration {version} failed: {exc}"
                        ) from exc
            self._initialized = True

    def integrity_check(self) -> bool:
        try:
            with self.connect() as connection:
                row = connection.execute("PRAGMA integrity_check").fetchone()
            return bool(row and row[0] == "ok")
        except DatabaseError:
            return False

    def backup(self, target: Path | str) -> Path:
        destination = Path(target)
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self.connect() as source:
                # sqlite3.Connection's context manager only commits on exit —
                # it never closes, which would leave the backup file locked
                # on Windows. closing() guarantees the handle is released.
                with contextlib.closing(sqlite3.connect(str(destination))) as backup:
                    source.backup(backup)
        except sqlite3.Error as exc:
            raise DatabaseError(f"Database backup failed: {exc}") from exc
        return destination
