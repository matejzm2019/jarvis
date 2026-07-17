"""Thread-safe assistant state."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
import logging
from threading import RLock


class AssistantStatus(str, Enum):
    SLEEPING = "sleeping"
    LISTENING = "listening"
    TRANSCRIBING = "transcribing"
    THINKING = "thinking"
    EXECUTING = "executing"
    SPEAKING = "speaking"
    MUTED = "muted"
    ERROR = "error"


@dataclass(slots=True)
class AssistantState:
    """Synchronized state holder with lightweight UI subscriptions."""

    _status: AssistantStatus = AssistantStatus.SLEEPING
    _lock: RLock = field(default_factory=RLock)
    _listeners: list[Callable[[AssistantStatus], None]] = field(default_factory=list)

    @property
    def status(self) -> AssistantStatus:
        with self._lock:
            return self._status

    def set(self, status: AssistantStatus) -> None:
        with self._lock:
            if status is self._status:
                return
            self._status = status
            listeners = tuple(self._listeners)
        for listener in listeners:
            try:
                listener(status)
            except Exception:
                logging.getLogger("jarvis.state").exception("Assistant state listener failed")

    def subscribe(self, listener: Callable[[AssistantStatus], None]) -> Callable[[], None]:
        """Register a state listener and return an unsubscribe callback."""
        with self._lock:
            self._listeners.append(listener)

        def unsubscribe() -> None:
            with self._lock:
                if listener in self._listeners:
                    self._listeners.remove(listener)

        return unsubscribe
