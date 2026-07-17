"""Native Windows global hotkeys for push-to-talk and speech interruption."""

from __future__ import annotations

import ctypes
import logging
import os
import threading
from collections.abc import Callable
from ctypes import wintypes

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

_MODIFIERS = {
    "alt": MOD_ALT,
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
    "windows": MOD_WIN,
}
_KEYS = {"space": 0x20, "enter": 0x0D, "escape": 0x1B, "esc": 0x1B, "tab": 0x09}


class HotkeyError(RuntimeError):
    """Invalid or unavailable native Windows hotkey."""


def parse_hotkey(value: str) -> tuple[int, int]:
    """Parse a constrained modifier-plus-key expression for RegisterHotKey."""
    parts = [part.strip().casefold() for part in value.split("+") if part.strip()]
    modifiers = MOD_NOREPEAT
    key: int | None = None
    for part in parts:
        if part in _MODIFIERS:
            modifiers |= _MODIFIERS[part]
            continue
        if key is not None:
            raise HotkeyError(f"Hotkey must contain exactly one non-modifier key: {value}")
        if part in _KEYS:
            key = _KEYS[part]
        elif len(part) == 1 and part.isascii() and part.isalnum():
            key = ord(part.upper())
        elif part.startswith("f") and part[1:].isdigit() and 1 <= int(part[1:]) <= 24:
            key = 0x6F + int(part[1:])
        else:
            raise HotkeyError(f"Unsupported hotkey key: {part}")
    if key is None:
        raise HotkeyError(f"Hotkey is missing a key: {value}")
    return modifiers, key


class _Point(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class _Message(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", _Point),
        ("lPrivate", wintypes.DWORD),
    ]


class GlobalHotkeyManager:
    """Own a Windows message thread and invoke callbacks without polling."""

    def __init__(self, bindings: dict[str, Callable[[], None]]) -> None:
        if not bindings:
            raise ValueError("At least one hotkey binding is required")
        self.bindings = bindings
        self.log = logging.getLogger("jarvis.audio.hotkeys")
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._ready = threading.Event()
        self._error: Exception | None = None

    def start(self) -> None:
        """Register all configured hotkeys on a native message thread."""
        if os.name != "nt":
            raise HotkeyError("Global hotkeys require Windows")
        if self._thread and self._thread.is_alive():
            return
        self._ready.clear()
        self._error = None
        self._thread = threading.Thread(target=self._message_loop, name="jarvis-hotkeys", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=3):
            raise HotkeyError("Windows hotkey thread did not start")
        if self._error:
            raise HotkeyError(str(self._error)) from self._error

    def stop(self) -> None:
        """Unregister hotkeys and stop the native message thread."""
        thread = self._thread
        if not thread:
            return
        if self._thread_id and os.name == "nt":
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        thread.join(timeout=3)
        self._thread = None
        self._thread_id = None

    def _message_loop(self) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        registered: list[int] = []
        indexed = list(enumerate(self.bindings.items(), start=1))
        try:
            self._thread_id = int(kernel32.GetCurrentThreadId())
            for hotkey_id, (expression, _) in indexed:
                modifiers, key = parse_hotkey(expression)
                if not user32.RegisterHotKey(None, hotkey_id, modifiers, key):
                    raise HotkeyError(f"Could not register global hotkey '{expression}'; it may already be in use")
                registered.append(hotkey_id)
            self._ready.set()
            callbacks = {hotkey_id: callback for hotkey_id, (_, callback) in indexed}
            message = _Message()
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                if message.message == WM_HOTKEY:
                    try:
                        callbacks[int(message.wParam)]()
                    except Exception:
                        self.log.exception("Hotkey callback failed")
        except Exception as exc:
            self._error = exc
            self._ready.set()
        finally:
            for hotkey_id in registered:
                user32.UnregisterHotKey(None, hotkey_id)
            self._ready.set()
