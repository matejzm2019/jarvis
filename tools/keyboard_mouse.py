"""Validated native Windows keyboard and mouse tools."""

from __future__ import annotations

import asyncio
import ctypes
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from assistant.models import RiskLevel, ToolResult
from tools.base import BaseTool

try:
    import win32api
    import win32con
except ImportError:  # pragma: no cover
    win32api = win32con = None  # type: ignore[assignment]

_KEYS = {
    "enter": 0x0D, "escape": 0x1B, "tab": 0x09, "space": 0x20, "backspace": 0x08,
    "delete": 0x2E, "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "ctrl": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B,
    **{f"f{index}": 0x6F + index for index in range(1, 13)},
}
_BLOCKED_HOTKEYS = {
    frozenset(("win", "r")), frozenset(("win", "x")), frozenset(("alt", "f4")),
    frozenset(("ctrl", "alt", "delete")), frozenset(("shift", "delete")),
    frozenset(("ctrl", "shift", "enter")),
}
_SECRET = re.compile(r"(?i)(password|passphrase|heslo|api[ _-]?key|access[ _-]?token|private[ _-]?key)\s*(?:is|je|:|=)")
_DANGEROUS_CLICK = re.compile(
    r"(?i)\b(purchase|buy|pay|payment|submit|send|confirm|delete|install|security warning|kúpiť|zaplatiť|odoslať|potvrdiť|vymazať|inštalovať|bezpečnostné upozornenie)\b"
)


def _key_code(name: str) -> int:
    key = name.casefold()
    if key in _KEYS:
        return _KEYS[key]
    if len(key) == 1 and key.isascii() and key.isalnum():
        return ord(key.upper())
    raise ValueError(f"Unsupported key: {name}")


class TypeTextArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=1000)


class KeyArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    key: str = Field(min_length=1, max_length=20)

    @field_validator("key")
    @classmethod
    def supported(cls, value: str) -> str:
        _key_code(value)
        return value.casefold()


class HotkeyArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    keys: list[str] = Field(min_length=2, max_length=4)

    @field_validator("keys")
    @classmethod
    def safe_keys(cls, values: list[str]) -> list[str]:
        normalized = [value.casefold().strip() for value in values]
        for value in normalized:
            _key_code(value)
        if len(set(normalized)) != len(normalized):
            raise ValueError("Hotkey keys must be distinct")
        if frozenset(normalized) in _BLOCKED_HOTKEYS:
            raise ValueError("This hotkey is blocked; use a dedicated registered tool instead")
        return normalized


class ClickArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    x: int
    y: int
    button: Literal["left", "right", "middle"] = "left"
    clicks: int = Field(default=1, ge=1, le=2)
    purpose: str = Field(min_length=3, max_length=200)

    @field_validator("purpose")
    @classmethod
    def reject_sensitive_actions(cls, value: str) -> str:
        if _DANGEROUS_CLICK.search(value):
            raise ValueError("Sensitive submit, purchase, delete, install, or security-warning clicks are not implemented")
        return value


class ScrollArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: int = Field(ge=-10, le=10)


class NativeInput:
    """Use predefined Win32 input primitives and validate screen/focus state."""

    @staticmethod
    def _password_field_focused() -> bool:
        class GuiThreadInfo(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.c_uint), ("flags", ctypes.c_uint),
                ("hwndActive", ctypes.c_void_p), ("hwndFocus", ctypes.c_void_p),
                ("hwndCapture", ctypes.c_void_p), ("hwndMenuOwner", ctypes.c_void_p),
                ("hwndMoveSize", ctypes.c_void_p), ("hwndCaret", ctypes.c_void_p),
                ("rcCaret", ctypes.c_long * 4),
            ]

        info = GuiThreadInfo(cbSize=ctypes.sizeof(GuiThreadInfo))
        if not ctypes.windll.user32.GetGUIThreadInfo(0, ctypes.byref(info)) or not info.hwndFocus:
            return False
        style = ctypes.windll.user32.GetWindowLongW(info.hwndFocus, -16)
        return bool(style & 0x20)

    @staticmethod
    def type_text(text: str) -> None:
        if _SECRET.search(text):
            raise ValueError("Typing passwords, keys, or tokens is forbidden")
        if NativeInput._password_field_focused():
            raise PermissionError("Refusing to type into a password field")
        class KeyboardInput(ctypes.Structure):
            _fields_ = [
                ("virtual_key", ctypes.c_ushort), ("scan_code", ctypes.c_ushort),
                ("flags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                ("extra_info", ctypes.c_size_t),
            ]

        class MouseInput(ctypes.Structure):
            _fields_ = [
                ("dx", ctypes.c_long), ("dy", ctypes.c_long),
                ("mouse_data", ctypes.c_ulong), ("flags", ctypes.c_ulong),
                ("time", ctypes.c_ulong), ("extra_info", ctypes.c_size_t),
            ]

        class HardwareInput(ctypes.Structure):
            _fields_ = [("message", ctypes.c_ulong), ("low", ctypes.c_ushort), ("high", ctypes.c_ushort)]

        class InputUnion(ctypes.Union):
            _fields_ = [("keyboard", KeyboardInput), ("mouse", MouseInput), ("hardware", HardwareInput)]

        class Input(ctypes.Structure):
            _fields_ = [("type", ctypes.c_ulong), ("value", InputUnion)]

        encoded = text.encode("utf-16-le")
        for index in range(0, len(encoded), 2):
            unit = int.from_bytes(encoded[index:index + 2], "little")
            events = (Input(type=1), Input(type=1))
            events[0].value.keyboard = KeyboardInput(0, unit, 0x0004, 0, 0)
            events[1].value.keyboard = KeyboardInput(0, unit, 0x0004 | 0x0002, 0, 0)
            array = (Input * 2)(*events)
            if ctypes.windll.user32.SendInput(2, array, ctypes.sizeof(Input)) != 2:
                raise ctypes.WinError()

    @staticmethod
    def press(keys: list[str]) -> None:
        if win32api is None or win32con is None:
            raise RuntimeError("pywin32 is required for keyboard input")
        codes = [_key_code(key) for key in keys]
        for code in codes:
            win32api.keybd_event(code, 0, 0, 0)
        for code in reversed(codes):
            win32api.keybd_event(code, 0, win32con.KEYEVENTF_KEYUP, 0)

    @staticmethod
    def _bounds() -> tuple[int, int, int, int]:
        if win32api is None:
            raise RuntimeError("pywin32 is required for mouse input")
        return tuple(win32api.GetSystemMetrics(index) for index in (76, 77, 78, 79))  # type: ignore[return-value]

    @staticmethod
    def click(arguments: ClickArguments) -> None:
        if win32api is None or win32con is None:
            raise RuntimeError("pywin32 is required for mouse input")
        left, top, width, height = NativeInput._bounds()
        if not (left <= arguments.x < left + width and top <= arguments.y < top + height):
            raise ValueError("Click coordinates are outside the current virtual desktop")
        flags = {
            "left": (win32con.MOUSEEVENTF_LEFTDOWN, win32con.MOUSEEVENTF_LEFTUP),
            "right": (win32con.MOUSEEVENTF_RIGHTDOWN, win32con.MOUSEEVENTF_RIGHTUP),
            "middle": (win32con.MOUSEEVENTF_MIDDLEDOWN, win32con.MOUSEEVENTF_MIDDLEUP),
        }[arguments.button]
        win32api.SetCursorPos((arguments.x, arguments.y))
        for _ in range(arguments.clicks):
            win32api.mouse_event(flags[0], 0, 0, 0, 0)
            win32api.mouse_event(flags[1], 0, 0, 0, 0)

    @staticmethod
    def scroll(amount: int) -> None:
        if win32api is None or win32con is None:
            raise RuntimeError("pywin32 is required for mouse input")
        win32api.mouse_event(win32con.MOUSEEVENTF_WHEEL, 0, 0, amount * 120, 0)


class TypeTextTool(BaseTool[TypeTextArguments]):
    name = "type_text"
    description = "Type non-sensitive text into the focused non-password control using native Unicode input."
    argument_model = TypeTextArguments
    risk = RiskLevel.MEDIUM

    async def execute(self, arguments: TypeTextArguments) -> ToolResult:
        await asyncio.to_thread(NativeInput.type_text, arguments.text)
        return ToolResult(success=True, tool=self.name, message=f"Typed {len(arguments.text)} characters.")


class PressKeyTool(BaseTool[KeyArguments]):
    name = "press_key"
    description = "Press one validated ordinary key."
    argument_model = KeyArguments
    risk = RiskLevel.MEDIUM

    async def execute(self, arguments: KeyArguments) -> ToolResult:
        await asyncio.to_thread(NativeInput.press, [arguments.key])
        return ToolResult(success=True, tool=self.name, message=f"Pressed {arguments.key}.")


class PressHotkeyTool(BaseTool[HotkeyArguments]):
    name = "press_hotkey"
    description = "Press a validated hotkey; dangerous launch, delete, elevated, and close combinations are blocked."
    argument_model = HotkeyArguments
    risk = RiskLevel.MEDIUM

    async def execute(self, arguments: HotkeyArguments) -> ToolResult:
        await asyncio.to_thread(NativeInput.press, arguments.keys)
        return ToolResult(success=True, tool=self.name, message=f"Pressed {'+'.join(arguments.keys)}.")


class ClickScreenPositionTool(BaseTool[ClickArguments]):
    name = "click_screen_position"
    description = "Click validated coordinates inside the current virtual desktop; sensitive actions are blocked."
    argument_model = ClickArguments
    risk = RiskLevel.MEDIUM

    async def execute(self, arguments: ClickArguments) -> ToolResult:
        await asyncio.to_thread(NativeInput.click, arguments)
        return ToolResult(success=True, tool=self.name, message=f"Clicked ({arguments.x}, {arguments.y}).")


class ScrollTool(BaseTool[ScrollArguments]):
    name = "scroll"
    description = "Scroll the focused window by a bounded number of wheel steps."
    argument_model = ScrollArguments
    risk = RiskLevel.MEDIUM

    async def execute(self, arguments: ScrollArguments) -> ToolResult:
        await asyncio.to_thread(NativeInput.scroll, arguments.amount)
        return ToolResult(success=True, tool=self.name, message=f"Scrolled {arguments.amount} steps.")


def build_input_tools() -> list[BaseTool]:
    return [TypeTextTool(), PressKeyTool(), PressHotkeyTool(), ClickScreenPositionTool(), ScrollTool()]
