"""Conversation facade around active-context management."""

from __future__ import annotations

from assistant.models import ChatMessage
from llm.context_manager import ContextManager
from memory.storage import MemoryStore


class Conversation:
    """Own user-visible turns while hiding tool-loop bookkeeping."""

    def __init__(self, context: ContextManager, memory: MemoryStore | None = None) -> None:
        self.context = context
        self.memory = memory

    def add_user(self, text: str) -> None:
        self.context.add(ChatMessage(role="user", content=text))
        if self.memory:
            self.memory.add_message("user", text)

    def add_assistant(self, text: str, *, persist: bool = True) -> None:
        self.context.add(ChatMessage(role="assistant", content=text))
        if self.memory and persist:
            self.memory.add_message("assistant", text)

    def clear(self) -> None:
        self.context.clear()
        if self.memory:
            self.memory.clear_history()
