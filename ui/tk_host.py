"""Main-thread tkinter host shared by every Jarvis local window."""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class _Command:
    callback: Callable[[Any], Any]
    event: threading.Event | None = None
    result: list[Any] | None = None


class TkHost:
    """Keep Tcl on the main thread and marshal tray callbacks through a queue."""

    def __init__(self) -> None:
        self._commands: queue.SimpleQueue[_Command] = queue.SimpleQueue()
        self._root: Any | None = None
        self._owner_id: int | None = None
        self.log = logging.getLogger("jarvis.ui.tk")

    def start(self) -> None:
        """Create the hidden root on the calling main thread."""
        if self._root is not None:
            return
        import tkinter as tk

        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("TkHost must start on the main thread")
        self._root = tk.Tk()
        self._root.withdraw()
        self._owner_id = threading.get_ident()

    def post(self, callback: Callable[[Any], Any]) -> None:
        """Queue a callback for the next main-thread UI pump."""
        if self._root is None:
            raise RuntimeError("TkHost is not running")
        self._commands.put(_Command(callback))

    def call(self, callback: Callable[[Any], Any], timeout: float | None = None) -> Any:
        """Run on the owner thread now, or queue and wait from another thread."""
        root = self._root
        if root is None:
            raise RuntimeError("TkHost is not running")
        if threading.get_ident() == self._owner_id:
            return callback(root)
        event = threading.Event()
        result: list[Any] = []
        self._commands.put(_Command(callback, event, result))
        if not event.wait(timeout):
            raise TimeoutError("Timed out waiting for the Jarvis UI")
        value = result[0]
        if isinstance(value, BaseException):
            raise value
        return value

    def poll(self) -> None:
        """Process queued commands and one tkinter event-loop iteration."""
        root = self._root
        if root is None:
            return
        if threading.get_ident() != self._owner_id:
            raise RuntimeError("TkHost.poll must run on its owner thread")
        try:
            while True:
                command = self._commands.get_nowait()
                try:
                    value: Any = command.callback(root)
                except BaseException as exc:
                    value = exc
                    self.log.exception("Tkinter command failed")
                if command.result is not None:
                    command.result.append(value)
                if command.event is not None:
                    command.event.set()
        except queue.Empty:
            pass
        root.update_idletasks()
        root.update()

    def stop(self) -> None:
        """Destroy Tcl on the same main thread where it was created."""
        root = self._root
        if root is None:
            return
        if threading.get_ident() != self._owner_id:
            raise RuntimeError("TkHost.stop must run on its owner thread")
        root.destroy()
        self._root = None
        self._owner_id = None
