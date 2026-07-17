"""Small local window showing the current Jarvis runtime state."""

from __future__ import annotations

from typing import Any

from assistant.state import AssistantState, AssistantStatus
from ui.tk_host import TkHost

_COLORS = {
    AssistantStatus.SLEEPING: "#64748b",
    AssistantStatus.LISTENING: "#22c55e",
    AssistantStatus.TRANSCRIBING: "#06b6d4",
    AssistantStatus.THINKING: "#8b5cf6",
    AssistantStatus.EXECUTING: "#f59e0b",
    AssistantStatus.SPEAKING: "#3b82f6",
    AssistantStatus.MUTED: "#94a3b8",
    AssistantStatus.ERROR: "#ef4444",
}


class StatusWindow:
    """Own one status Toplevel on the shared tkinter thread."""

    def __init__(self, state: AssistantState, host: TkHost) -> None:
        self.state = state
        self.host = host
        self._window: Any | None = None
        self._label: Any | None = None
        self._unsubscribe = state.subscribe(
            lambda status: self.host.post(lambda root: self._set_status(status))
        )

    def open(self) -> None:
        """Open or focus the status window."""
        self.host.post(self._open)

    def _open(self, root: Any) -> None:
        import tkinter as tk

        if self._window is not None and self._window.winfo_exists():
            self._window.deiconify()
            self._window.lift()
            self._window.focus_force()
            return
        window = tk.Toplevel(root)
        self._window = window
        window.title("Jarvis status")
        window.geometry("340x170")
        window.resizable(False, False)
        window.configure(bg="#0f172a")
        window.protocol("WM_DELETE_WINDOW", self._destroy)
        tk.Label(
            window, text="JARVIS", fg="#e2e8f0", bg="#0f172a", font=("Segoe UI", 20, "bold")
        ).pack(pady=(24, 8))
        self._label = tk.Label(window, font=("Segoe UI", 15, "bold"), bg="#0f172a")
        self._label.pack()
        self._set_status(self.state.status)

    def _set_status(self, status: AssistantStatus) -> None:
        if self._label is not None and self._label.winfo_exists():
            self._label.configure(text=status.value.upper(), fg=_COLORS[status])

    def _destroy(self) -> None:
        if self._window is not None:
            self._window.destroy()
        self._window = None
        self._label = None

    def close(self) -> None:
        """Destroy the Toplevel on its owner thread and unsubscribe."""
        self._unsubscribe()
        self.host.call(lambda root: self._destroy(), timeout=3)
