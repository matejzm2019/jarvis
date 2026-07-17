"""Windows system tray adapter for Jarvis Phase 3."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from assistant.state import AssistantState, AssistantStatus

_STATUS_COLORS = {
    AssistantStatus.SLEEPING: "#64748b",
    AssistantStatus.LISTENING: "#22c55e",
    AssistantStatus.TRANSCRIBING: "#06b6d4",
    AssistantStatus.THINKING: "#8b5cf6",
    AssistantStatus.EXECUTING: "#f59e0b",
    AssistantStatus.SPEAKING: "#3b82f6",
    AssistantStatus.MUTED: "#94a3b8",
    AssistantStatus.ERROR: "#ef4444",
}


@dataclass(frozen=True, slots=True)
class TrayCallbacks:
    """Synchronous callbacks marshalled by the desktop controller."""

    start_listening: Callable[[], None]
    stop_listening: Callable[[], None]
    push_to_talk: Callable[[], None]
    toggle_mute: Callable[[], None]
    stop_speaking: Callable[[], None]
    open_settings: Callable[[], None]
    open_status: Callable[[], None]
    open_logs: Callable[[], None]
    clear_history: Callable[[], None]
    restart: Callable[[], None]
    quit: Callable[[], None]
    is_muted: Callable[[], bool]
    is_listening: Callable[[], bool]


def create_status_icon(status: AssistantStatus, size: int = 64) -> Any:
    """Create a high-contrast local tray image without external assets."""
    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (size, size), (15, 23, 42, 255))
    draw = ImageDraw.Draw(image)
    margin = max(3, size // 14)
    draw.ellipse((margin, margin, size - margin, size - margin), fill=_STATUS_COLORS[status], outline="white", width=2)
    line = max(2, size // 12)
    draw.line((size * 0.36, size * 0.25, size * 0.36, size * 0.63), fill="white", width=line)
    draw.arc((size * 0.36, size * 0.38, size * 0.68, size * 0.74), 0, 100, fill="white", width=line)
    return image


class TrayApplication:
    """Own the pystray icon, state colors, notifications, and menu."""

    def __init__(self, state: AssistantState, callbacks: TrayCallbacks) -> None:
        self.state = state
        self.callbacks = callbacks
        self._icon: Any | None = None
        self._thread: threading.Thread | None = None
        self._unsubscribe = state.subscribe(self._update_status)
        self.log = logging.getLogger("jarvis.ui.tray")

    def _call(self, callback: Callable[[], None]) -> Callable[..., None]:
        def invoke(*_: Any) -> None:
            try:
                callback()
            except Exception:
                self.log.exception("Tray action failed")

        return invoke

    def start(self) -> None:
        """Start the Windows tray message loop on its own thread."""
        if self._thread and self._thread.is_alive():
            return
        import pystray

        menu = pystray.Menu(
            pystray.MenuItem("Open status", self._call(self.callbacks.open_status), default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Start listening", self._call(self.callbacks.start_listening), enabled=lambda _: not self.callbacks.is_listening()),
            pystray.MenuItem("Stop listening", self._call(self.callbacks.stop_listening), enabled=lambda _: self.callbacks.is_listening()),
            pystray.MenuItem("Push to talk", self._call(self.callbacks.push_to_talk)),
            pystray.MenuItem("Mute assistant", self._call(self.callbacks.toggle_mute), checked=lambda _: self.callbacks.is_muted()),
            pystray.MenuItem("Stop speaking", self._call(self.callbacks.stop_speaking)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open settings", self._call(self.callbacks.open_settings)),
            pystray.MenuItem("Open logs", self._call(self.callbacks.open_logs)),
            pystray.MenuItem("Clear conversation history", self._call(self.callbacks.clear_history)),
            pystray.MenuItem("Restart assistant", self._call(self.callbacks.restart)),
            pystray.MenuItem("Quit", self._call(self.callbacks.quit)),
        )
        status = self.state.status
        self._icon = pystray.Icon("jarvis", create_status_icon(status), f"Jarvis — {status.value}", menu)
        self._thread = threading.Thread(target=self._icon.run, name="jarvis-tray", daemon=True)
        self._thread.start()

    def _update_status(self, status: AssistantStatus) -> None:
        icon = self._icon
        if icon is None:
            return
        try:
            icon.icon = create_status_icon(status)
            icon.title = f"Jarvis — {status.value}"
            icon.update_menu()
        except Exception:
            self.log.exception("Could not update tray status")

    def notify(self, title: str, message: str) -> None:
        """Show a Windows notification through the active tray icon."""
        if self._icon is None:
            self.log.info("Notification before tray startup: %s", message)
            return
        self._icon.notify(message, title)

    def refresh_menu(self) -> None:
        """Refresh dynamic checked and enabled menu state."""
        if self._icon is not None:
            self._icon.update_menu()

    def stop(self) -> None:
        """Stop the icon message loop and detach state listeners."""
        self._unsubscribe()
        icon, thread = self._icon, self._thread
        self._icon = None
        self._thread = None
        if icon is not None:
            icon.stop()
        if thread and thread is not threading.current_thread():
            thread.join(timeout=3)
