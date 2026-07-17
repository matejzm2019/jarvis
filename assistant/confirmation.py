"""Local permission notification and confirmation adapters."""

from __future__ import annotations

import asyncio
from typing import Protocol

from ui.notifications import NotificationCenter
from ui.tk_host import TkHost


class ConfirmationService(Protocol):
    async def notify(self, message: str) -> None: ...
    async def confirm(self, message: str) -> bool: ...


class ConsoleConfirmationService:
    """Phase 1 console adapter; tray dialogs replace it in Phase 3."""

    async def notify(self, message: str) -> None:
        print(f"[Action] {message}")

    async def confirm(self, message: str) -> bool:
        answer = await asyncio.to_thread(input, f"[Confirmation required] {message} [y/N]: ")
        return answer.strip().casefold() in {"y", "yes", "áno", "ano"}


class TkConfirmationService:
    """Use tray notifications for medium risk and a local dialog for high risk."""

    def __init__(self, notifications: NotificationCenter, host: TkHost) -> None:
        self.notifications = notifications
        self.host = host

    async def notify(self, message: str) -> None:
        self.notifications.notify(message, "Jarvis action")

    async def confirm(self, message: str) -> bool:
        return bool(
            await asyncio.to_thread(
                self.host.call, lambda root: self._confirm_dialog(root, message), None
            )
        )

    @staticmethod
    def _confirm_dialog(root: object, message: str) -> bool:
        import tkinter as tk
        from tkinter import messagebox

        parent = tk.Toplevel(root)
        parent.withdraw()
        parent.attributes("-topmost", True)
        try:
            return bool(messagebox.askyesno("Jarvis confirmation", message, parent=parent))
        finally:
            parent.destroy()
