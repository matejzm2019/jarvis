"""Thread-safe local notification routing for the Windows tray."""

from __future__ import annotations

import logging
from collections.abc import Callable
from threading import RLock


class NotificationCenter:
    """Send local notifications through the attached tray icon."""

    def __init__(self) -> None:
        self._sender: Callable[[str, str], None] | None = None
        self._lock = RLock()
        self.log = logging.getLogger("jarvis.ui.notifications")

    def attach(self, sender: Callable[[str, str], None]) -> None:
        """Attach a tray notification sender."""
        with self._lock:
            self._sender = sender

    def detach(self) -> None:
        """Detach the current tray sender."""
        with self._lock:
            self._sender = None

    def notify(self, message: str, title: str = "Jarvis") -> None:
        """Display a private local notification or log it if the tray is unavailable."""
        with self._lock:
            sender = self._sender
        if sender is None:
            self.log.info("Notification: %s", message)
            return
        try:
            sender(title, message)
        except Exception:
            self.log.exception("Tray notification failed")
