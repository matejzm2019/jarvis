"""Privacy-filtered persistent memory operations."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Literal

from memory.database import MemoryDatabase

AliasKind = Literal["application", "folder"]
_SECRET = re.compile(
    r"(?i)(password|passphrase|heslo|api[ _-]?key|access[ _-]?token|refresh[ _-]?token|private[ _-]?key|cookie)\s*(?:is|je|:|=)"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----|\bsk-[A-Za-z0-9_-]{16,}|\bBearer\s+[A-Za-z0-9._~-]{12,}|\beyJ[A-Za-z0-9_-]{12,}\."
)


def validate_memory_text(value: str, *, maximum: int = 2000) -> str:
    """Reject secrets, control characters, and oversized permanent-memory values."""
    text = " ".join(value.strip().split())
    if not text:
        raise ValueError("Memory value cannot be empty")
    if len(text) > maximum:
        raise ValueError(f"Memory value exceeds {maximum} characters")
    if _SECRET.search(text):
        raise ValueError("Passwords, keys, tokens, and authentication data cannot be stored")
    return text


class MemoryStore:
    """Store bounded history and explicitly approved permanent memory in SQLite."""

    def __init__(self, path: str | Path, max_history: int = 200) -> None:
        self.database = MemoryDatabase(path)
        self.max_history = max_history

    @property
    def path(self) -> Path:
        return self.database.path

    def add_message(self, role: Literal["user", "assistant"], content: str) -> None:
        text = content.strip()
        if not text or _SECRET.search(text):
            return

        def write(connection: sqlite3.Connection) -> None:
            connection.execute("INSERT INTO conversation(role, content) VALUES (?, ?)", (role, text))
            connection.execute(
                "DELETE FROM conversation WHERE id NOT IN (SELECT id FROM conversation ORDER BY id DESC LIMIT ?)",
                (self.max_history,),
            )

        self.database.transaction(write)

    def recent_messages(self, limit: int) -> list[dict[str, str]]:
        if limit <= 0:
            return []

        def read(connection: sqlite3.Connection) -> list[dict[str, str]]:
            rows = connection.execute(
                "SELECT role, content, created_at FROM conversation ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(row) for row in reversed(rows)]

        return self.database.transaction(read)

    def clear_history(self) -> int:
        def clear(connection: sqlite3.Connection) -> int:
            count = connection.execute("SELECT COUNT(*) FROM conversation").fetchone()[0]
            connection.execute("DELETE FROM conversation")
            return int(count)

        return self.database.transaction(clear)

    def set_preference(self, key: str, value: str) -> None:
        safe_key = validate_memory_text(key, maximum=80)
        safe_value = validate_memory_text(value, maximum=500)
        self.database.transaction(
            lambda connection: connection.execute(
                "INSERT INTO preferences(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP",
                (safe_key, safe_value),
            )
        )

    def preferences(self) -> dict[str, str]:
        return self.database.transaction(
            lambda connection: {
                str(row["key"]): str(row["value"])
                for row in connection.execute("SELECT key, value FROM preferences ORDER BY key")
            }
        )

    def clear_preferences(self) -> int:
        def clear(connection: sqlite3.Connection) -> int:
            count = connection.execute("SELECT COUNT(*) FROM preferences").fetchone()[0]
            connection.execute("DELETE FROM preferences")
            return int(count)

        return self.database.transaction(clear)

    def remember_fact(self, fact: str) -> int:
        safe = validate_memory_text(fact)

        def write(connection: sqlite3.Connection) -> int:
            connection.execute("INSERT OR IGNORE INTO facts(fact) VALUES (?)", (safe,))
            row = connection.execute("SELECT id FROM facts WHERE fact = ? COLLATE NOCASE", (safe,)).fetchone()
            return int(row[0])

        return self.database.transaction(write)

    def facts(self) -> list[dict[str, str | int]]:
        return self.database.transaction(
            lambda connection: [dict(row) for row in connection.execute(
                "SELECT id, fact, created_at FROM facts ORDER BY id"
            )]
        )

    def forget_fact(self, query: str) -> int:
        safe = validate_memory_text(query, maximum=500)

        def remove(connection: sqlite3.Connection) -> int:
            cursor = connection.execute("DELETE FROM facts WHERE fact LIKE ?", (f"%{safe}%",))
            return cursor.rowcount

        return self.database.transaction(remove)

    def set_alias(self, kind: AliasKind, alias: str, target: str) -> None:
        safe_alias = validate_memory_text(alias, maximum=80)
        safe_target = validate_memory_text(target, maximum=1024)
        self.database.transaction(
            lambda connection: connection.execute(
                "INSERT INTO aliases(kind, alias, target) VALUES (?, ?, ?) "
                "ON CONFLICT(kind, alias) DO UPDATE SET target=excluded.target, updated_at=CURRENT_TIMESTAMP",
                (kind, safe_alias, safe_target),
            )
        )

    def aliases(self, kind: AliasKind) -> dict[str, str]:
        return self.database.transaction(
            lambda connection: {
                str(row["alias"]): str(row["target"])
                for row in connection.execute("SELECT alias, target FROM aliases WHERE kind = ?", (kind,))
            }
        )
