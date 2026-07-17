"""Bounded SQLite-backed short-term conversation history."""

from assistant.models import ChatMessage
from memory.storage import MemoryStore


def restore_messages(store: MemoryStore, limit: int) -> list[ChatMessage]:
    """Restore only bounded user/assistant turns, never historical tool payloads."""
    return [ChatMessage(role=item["role"], content=item["content"]) for item in store.recent_messages(limit)]
