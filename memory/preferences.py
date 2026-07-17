"""Preference view backed by the shared local memory store."""

from memory.storage import MemoryStore


class PreferenceMemory:
    """Expose approved preferences to active conversation context."""

    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    def all(self) -> dict[str, str]:
        return self.store.preferences()
