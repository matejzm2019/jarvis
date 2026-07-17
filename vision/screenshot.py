"""On-demand virtual-desktop capture through mss."""

from __future__ import annotations

import ctypes
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import dataclass, field
from typing import Any, Literal

from PIL import Image


class ScreenCaptureError(RuntimeError):
    """Screen capture was unavailable or produced invalid bounds."""


def cursor_position() -> tuple[int, int] | None:
    """Read the current cursor position without moving it."""
    try:
        import win32api

        x, y = win32api.GetCursorPos()
        return int(x), int(y)
    except Exception:
        try:
            point = wintypes.POINT()
            if ctypes.windll.user32.GetCursorPos(ctypes.byref(point)):
                return int(point.x), int(point.y)
        except Exception:
            pass
        return None


@dataclass(slots=True)
class ScreenCapture:
    """In-memory screenshot plus trusted Windows metadata."""

    image: Image.Image
    source: Literal["screen", "active_window"]
    left: int
    top: int
    virtual_screen: dict[str, int]
    cursor: tuple[int, int] | None = None
    window: dict[str, Any] | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def width(self) -> int:
        return self.image.width

    @property
    def height(self) -> int:
        return self.image.height

    def metadata(self) -> dict[str, Any]:
        """Return JSON-safe metadata without pixel data or private file paths."""
        data: dict[str, Any] = {
            "source": self.source,
            "bounds": {"left": self.left, "top": self.top, "width": self.width, "height": self.height},
            "virtual_screen": self.virtual_screen,
            "cursor": {"x": self.cursor[0], "y": self.cursor[1]} if self.cursor else None,
        }
        if self.window:
            data["active_window"] = self.window
        data.update(self.extra)
        return data

    def close(self) -> None:
        """Release pixel memory immediately after local analysis."""
        self.image.close()


class ScreenCaptureService:
    """Capture the full virtual desktop or a validated region only on request."""

    def __init__(self, mss_factory: Callable[[], Any] | None = None) -> None:
        self._mss_factory = mss_factory

    def _factory(self) -> Callable[[], Any]:
        if self._mss_factory is not None:
            return self._mss_factory
        try:
            import mss
        except ImportError as exc:
            raise ScreenCaptureError("mss is not installed") from exc
        return mss.MSS

    @staticmethod
    def _bounds(raw: Any) -> dict[str, int]:
        return {name: int(raw[name]) for name in ("left", "top", "width", "height")}

    def capture_screen(self) -> ScreenCapture:
        """Capture all monitors as one virtual desktop image."""
        try:
            with self._factory()() as capture:
                virtual = self._bounds(capture.monitors[0])
                return self._grab(capture, virtual, "screen", virtual)
        except ScreenCaptureError:
            raise
        except Exception as exc:
            raise ScreenCaptureError(f"Could not capture the screen: {exc}") from exc

    def capture_region(
        self,
        region: dict[str, int],
        *,
        source: Literal["screen", "active_window"] = "active_window",
        window: dict[str, Any] | None = None,
    ) -> ScreenCapture:
        """Clamp and capture a region inside the current virtual desktop."""
        try:
            with self._factory()() as capture:
                virtual = self._bounds(capture.monitors[0])
                left = max(int(region["left"]), virtual["left"])
                top = max(int(region["top"]), virtual["top"])
                right = min(int(region["left"]) + int(region["width"]), virtual["left"] + virtual["width"])
                bottom = min(int(region["top"]) + int(region["height"]), virtual["top"] + virtual["height"])
                if right <= left or bottom <= top:
                    raise ScreenCaptureError("Requested capture region is outside the virtual desktop")
                bounded = {"left": left, "top": top, "width": right - left, "height": bottom - top}
                return self._grab(capture, bounded, source, virtual, window)
        except ScreenCaptureError:
            raise
        except Exception as exc:
            raise ScreenCaptureError(f"Could not capture the requested region: {exc}") from exc

    @staticmethod
    def _grab(
        capture: Any,
        region: dict[str, int],
        source: Literal["screen", "active_window"],
        virtual: dict[str, int],
        window: dict[str, Any] | None = None,
    ) -> ScreenCapture:
        shot = capture.grab(region)
        image = Image.frombytes("RGB", (region["width"], region["height"]), shot.rgb)
        return ScreenCapture(
            image=image,
            source=source,
            left=region["left"],
            top=region["top"],
            virtual_screen=virtual,
            cursor=cursor_position(),
            window=window,
        )
