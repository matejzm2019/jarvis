"""SQLite connection and schema for local Jarvis memory."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

T = TypeVar("T")


class MemoryDatabase:
    """Own the local SQLite schema and serialize short transactions."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve(strict=False)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def transaction(self, operation: Callable[[sqlite3.Connection], T]) -> T:
        """Run one committed operation under the process-local database lock."""
        with self._lock, self._connect() as connection:
            return operation(connection)

    def _initialize(self) -> None:
        def create(connection: sqlite3.Connection) -> None:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversation (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS preferences (
                    key TEXT PRIMARY KEY COLLATE NOCASE,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS aliases (
                    kind TEXT NOT NULL CHECK(kind IN ('application', 'folder')),
                    alias TEXT NOT NULL COLLATE NOCASE,
                    target TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(kind, alias)
                );
                CREATE TABLE IF NOT EXISTS facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fact TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

        self.transaction(create)
