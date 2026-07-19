"""Validated native Windows window, desktop, and volume controls."""

from __future__ import annotations

import asyncio
import ctypes
from pathlib import Path
from typing import Any

import psutil
from pydantic import BaseModel, ConfigDict, Field
from rapidfuzz import fuzz

from assistant.models import RiskLevel, ToolResult
from tools.applications import ApplicationCatalog
from tools.base import BaseTool, EmptyArguments
from tools.media_controls import VolumeArguments

try:
    import win32api
    import win32con
    import win32gui
    import win32process
except ImportError:  # pragma: no cover
    win32api = win32con = win32gui = win32process = None  # type: ignore[assignment]


class WindowArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    target: str | None = Field(default=None, min_length=1, max_length=200)


class WindowService:
    """Resolve real visible windows without accepting model-generated handles."""

    @staticmethod
    def windows() -> list[dict[str, Any]]:
        if win32gui is None or win32process is None:
            raise RuntimeError("pywin32 is required for window controls")
        items: list[dict[str, Any]] = []

        def collect(hwnd: int, _: object) -> None:
            if not win32gui.IsWindowVisible(hwnd):
                return
            title = win32gui.GetWindowText(hwnd).strip()
            if not title:
                return
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            try:
                application = psutil.Process(pid).name()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                application = "unknown"
            items.append({"handle": hwnd, "title": title, "application": application, "pid": pid})

        win32gui.EnumWindows(collect, None)
        return items

    def resolve(self, target: str | None) -> dict[str, Any]:
        if not target:
            return ApplicationCatalog.foreground()
        scored = sorted(
            [
                (
                max(fuzz.WRatio(target.casefold(), item["title"].casefold()),
                    fuzz.WRatio(target.casefold(), Path(item["application"]).stem.casefold())),
                item,
                )
                for item in self.windows()
            ],
            key=lambda pair: pair[0],
        )
        if not scored or scored[-1][0] < 65:
            raise FileNotFoundError(f"No visible window matches '{target}'")
        if len(scored) > 1 and scored[-1][0] - scored[-2][0] < 3:
            raise ValueError(f"Window target '{target}' is ambiguous")
        return scored[-1][1]

    def show(self, target: str | None, command: int) -> dict[str, Any]:
        item = self.resolve(target)
        win32gui.ShowWindow(item["handle"], command)
        return item

    def focus(self, target: str | None) -> dict[str, Any]:
        item = self.resolve(target)
        win32gui.ShowWindow(item["handle"], win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(item["handle"])
        return item

    def close(self, target: str | None) -> dict[str, Any]:
        item = self.resolve(target)
        win32gui.PostMessage(item["handle"], win32con.WM_CLOSE, 0, 0)
        return item


class GetActiveWindowTool(BaseTool[EmptyArguments]):
    name = "get_active_window"
    description = "Get the actual active Windows window title, application, process ID, and handle."
    argument_model = EmptyArguments

    async def execute(self, arguments: EmptyArguments) -> ToolResult:
        data = await asyncio.to_thread(ApplicationCatalog.foreground)
        return ToolResult(success=True, tool=self.name, message=f"Active window: {data['title'] or data['application']}.", data=data)


class _WindowTool(BaseTool[WindowArguments]):
    argument_model = WindowArguments
    risk = RiskLevel.MEDIUM
    command: int

    def __init__(self, service: WindowService) -> None:
        super().__init__()
        self.service = service

    async def execute(self, arguments: WindowArguments) -> ToolResult:
        data = await asyncio.to_thread(self.service.show, arguments.target, self.command)
        return ToolResult(success=True, tool=self.name, message=f"Updated window {data['title']}.", data=data)


class MinimizeWindowTool(_WindowTool):
    name = "minimize_window"
    description = "Minimize a uniquely matched visible window, or the active window when target is omitted."
    command = 6


class MaximizeWindowTool(_WindowTool):
    name = "maximize_window"
    description = "Maximize a uniquely matched visible window, or the active window when target is omitted."
    command = 3


class RestoreWindowTool(_WindowTool):
    name = "restore_window"
    description = "Restore a uniquely matched visible window, or the active window when target is omitted."
    command = 9


class FocusWindowTool(BaseTool[WindowArguments]):
    name = "focus_window"
    description = "Focus a uniquely matched visible window without using a model-generated handle."
    argument_model = WindowArguments
    risk = RiskLevel.MEDIUM

    def __init__(self, service: WindowService) -> None:
        super().__init__()
        self.service = service

    async def execute(self, arguments: WindowArguments) -> ToolResult:
        data = await asyncio.to_thread(self.service.focus, arguments.target)
        return ToolResult(success=True, tool=self.name, message=f"Focused {data['title']}.", data=data)


class SwitchWindowTool(FocusWindowTool):
    name = "switch_window"
    description = "Switch to a uniquely matched visible window."


class CloseWindowTool(BaseTool[WindowArguments]):
    name = "close_window"
    description = "Request graceful close of one uniquely matched visible window; never force-kill its process."
    argument_model = WindowArguments
    risk = RiskLevel.MEDIUM

    def __init__(self, service: WindowService) -> None:
        super().__init__()
        self.service = service

    async def execute(self, arguments: WindowArguments) -> ToolResult:
        data = await asyncio.to_thread(self.service.close, arguments.target)
        return ToolResult(success=True, tool=self.name, message=f"Requested close for {data['title']}.", data=data)


class SystemVolume:
    """Use Windows Core Audio without shell commands."""

    @staticmethod
    def endpoint() -> Any:
        from pycaw.pycaw import AudioUtilities

        return AudioUtilities.GetSpeakers().EndpointVolume

    def set(self, percent: int) -> int:
        endpoint = self.endpoint()
        endpoint.SetMasterVolumeLevelScalar(percent / 100, None)
        if percent:
            endpoint.SetMute(False, None)
        return percent

    def adjust(self, delta: int) -> int:
        endpoint = self.endpoint()
        current = round(endpoint.GetMasterVolumeLevelScalar() * 100)
        return self.set(max(0, min(100, current + delta)))

    def mute(self) -> None:
        self.endpoint().SetMute(True, None)

    def unmute(self) -> None:
        self.endpoint().SetMute(False, None)


class SetVolumeTool(BaseTool[VolumeArguments]):
    name = "set_volume"
    description = "Set Windows system output volume from 0 to 100 percent."
    argument_model = VolumeArguments
    risk = RiskLevel.MEDIUM

    def __init__(self, volume: SystemVolume) -> None:
        super().__init__()
        self.volume = volume

    async def execute(self, arguments: VolumeArguments) -> ToolResult:
        percent = await asyncio.to_thread(self.volume.set, arguments.percent)
        return ToolResult(success=True, tool=self.name, message=f"Set system volume to {percent}%.", data={"percent": percent})


class _AdjustVolumeTool(BaseTool[EmptyArguments]):
    argument_model = EmptyArguments
    risk = RiskLevel.MEDIUM
    delta: int

    def __init__(self, volume: SystemVolume) -> None:
        super().__init__()
        self.volume = volume

    async def execute(self, arguments: EmptyArguments) -> ToolResult:
        percent = await asyncio.to_thread(self.volume.adjust, self.delta)
        return ToolResult(success=True, tool=self.name, message=f"System volume is {percent}%.", data={"percent": percent})


class VolumeUpTool(_AdjustVolumeTool):
    name = "volume_up"
    description = "Increase Windows system output volume by 5 percentage points."
    delta = 5


class VolumeDownTool(_AdjustVolumeTool):
    name = "volume_down"
    description = "Decrease Windows system output volume by 5 percentage points."
    delta = -5


class MuteVolumeTool(BaseTool[EmptyArguments]):
    name = "mute_volume"
    description = "Mute Windows system output volume."
    argument_model = EmptyArguments
    risk = RiskLevel.MEDIUM

    def __init__(self, volume: SystemVolume) -> None:
        super().__init__()
        self.volume = volume

    async def execute(self, arguments: EmptyArguments) -> ToolResult:
        await asyncio.to_thread(self.volume.mute)
        return ToolResult(success=True, tool=self.name, message="Muted system volume.")


class UnmuteVolumeTool(MuteVolumeTool):
    name = "unmute_volume"
    description = "Unmute Windows system output volume."

    async def execute(self, arguments: EmptyArguments) -> ToolResult:
        await asyncio.to_thread(self.volume.unmute)
        return ToolResult(success=True, tool=self.name, message="Unmuted system volume.")


class ShowDesktopTool(BaseTool[EmptyArguments]):
    name = "show_desktop"
    description = "Show the Windows desktop using the predefined Win+D shortcut."
    argument_model = EmptyArguments

    @staticmethod
    def _show() -> None:
        if win32api is None or win32con is None:
            raise RuntimeError("pywin32 is required")
        win32api.keybd_event(win32con.VK_LWIN, 0, 0, 0)
        win32api.keybd_event(ord("D"), 0, 0, 0)
        win32api.keybd_event(ord("D"), 0, win32con.KEYEVENTF_KEYUP, 0)
        win32api.keybd_event(win32con.VK_LWIN, 0, win32con.KEYEVENTF_KEYUP, 0)

    async def execute(self, arguments: EmptyArguments) -> ToolResult:
        await asyncio.to_thread(self._show)
        return ToolResult(success=True, tool=self.name, message="Showed the desktop.")


class LockComputerTool(BaseTool[EmptyArguments]):
    name = "lock_computer"
    description = "Lock the current Windows workstation after explicit local confirmation."
    argument_model = EmptyArguments
    risk = RiskLevel.HIGH

    async def execute(self, arguments: EmptyArguments) -> ToolResult:
        if not ctypes.windll.user32.LockWorkStation():
            raise ctypes.WinError()
        return ToolResult(success=True, tool=self.name, message="Locked the computer.")


def build_window_tools() -> list[BaseTool]:
    """Build native window, desktop, and system-volume tools."""
    windows = WindowService()
    volume = SystemVolume()
    return [
        GetActiveWindowTool(), MinimizeWindowTool(windows), MaximizeWindowTool(windows),
        RestoreWindowTool(windows), CloseWindowTool(windows), SwitchWindowTool(windows),
        FocusWindowTool(windows), SetVolumeTool(volume), VolumeUpTool(volume),
        VolumeDownTool(volume), MuteVolumeTool(volume), UnmuteVolumeTool(volume),
        LockComputerTool(), ShowDesktopTool(),
    ]
