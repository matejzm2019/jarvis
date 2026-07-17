"""Windows foreground-window bounds and screenshot capture."""

from __future__ import annotations

import ctypes
from collections.abc import Callable
from ctypes import wintypes
from typing import Any

from tools.applications import ApplicationCatalog
from vision.screenshot import ScreenCapture, ScreenCaptureError, ScreenCaptureService

DWMWA_EXTENDED_FRAME_BOUNDS = 9


def foreground_window_rect(handle: int) -> dict[str, int]:
    """Return DWM frame bounds, falling back to the Win32 window rectangle."""
    rect = wintypes.RECT()
    try:
        result = ctypes.windll.dwmapi.DwmGetWindowAttribute(
            handle, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(rect), ctypes.sizeof(rect)
        )
        if result != 0:
            raise OSError(f"DwmGetWindowAttribute returned {result}")
        left, top, right, bottom = rect.left, rect.top, rect.right, rect.bottom
    except Exception:
        try:
            import win32gui

            left, top, right, bottom = win32gui.GetWindowRect(handle)
        except Exception as exc:
            raise ScreenCaptureError(f"Could not read active-window bounds: {exc}") from exc
    width, height = int(right - left), int(bottom - top)
    if width <= 0 or height <= 0:
        raise ScreenCaptureError("The active window has empty bounds")
    return {"left": int(left), "top": int(top), "width": width, "height": height}


class ActiveWindowCaptureService:
    """Capture only the visible foreground window using trusted Win32 metadata."""

    def __init__(
        self,
        screenshots: ScreenCaptureService | None = None,
        info_provider: Callable[[], dict[str, Any]] = ApplicationCatalog.foreground,
        rect_provider: Callable[[int], dict[str, int]] = foreground_window_rect,
    ) -> None:
        self.screenshots = screenshots or ScreenCaptureService()
        self.info_provider = info_provider
        self.rect_provider = rect_provider

    def capture(self) -> ScreenCapture:
        """Capture the active window or fail without falling back to the full screen."""
        try:
            window = self.info_provider()
            handle = int(window["handle"])
            try:
                import win32gui

                if win32gui.IsIconic(handle):
                    raise ScreenCaptureError("The active window is minimized")
            except ImportError:
                pass
            region = self.rect_provider(handle)
            return self.screenshots.capture_region(region, source="active_window", window=window)
        except ScreenCaptureError:
            raise
        except Exception as exc:
            raise ScreenCaptureError(f"Could not capture the active window: {exc}") from exc
