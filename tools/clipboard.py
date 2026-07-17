"""Explicit privacy-gated Windows clipboard tools."""

from __future__ import annotations

import asyncio

from pydantic import BaseModel, ConfigDict, Field

from assistant.models import RiskLevel, ToolResult
from memory.storage import validate_memory_text
from tools.base import BaseTool, EmptyArguments

try:
    import win32clipboard
    import win32con
except ImportError:  # pragma: no cover
    win32clipboard = win32con = None  # type: ignore[assignment]


class ClipboardTextArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=100_000)


class ClipboardService:
    """Read/write text without logging or persisting clipboard contents."""

    @staticmethod
    def get_text() -> str:
        if win32clipboard is None or win32con is None:
            raise RuntimeError("pywin32 clipboard support is unavailable")
        win32clipboard.OpenClipboard()
        try:
            if not win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                raise ValueError("Clipboard does not contain Unicode text")
            return str(win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT))[:100_000]
        finally:
            win32clipboard.CloseClipboard()

    @staticmethod
    def set_text(text: str) -> None:
        validate_memory_text(text, maximum=100_000)
        if win32clipboard is None or win32con is None:
            raise RuntimeError("pywin32 clipboard support is unavailable")
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
        finally:
            win32clipboard.CloseClipboard()


class GetClipboardTextTool(BaseTool[EmptyArguments]):
    name = "get_clipboard_text"
    description = "Read clipboard text only after an explicit user request; never persist or log the content."
    argument_model = EmptyArguments
    risk = RiskLevel.MEDIUM

    async def execute(self, arguments: EmptyArguments) -> ToolResult:
        text = await asyncio.to_thread(ClipboardService.get_text)
        return ToolResult(success=True, tool=self.name, message="Read clipboard text.", data={"text": text})


class SetClipboardTextTool(BaseTool[ClipboardTextArguments]):
    name = "set_clipboard_text"
    description = "Replace clipboard text with validated non-secret text; contents are never logged or persisted."
    argument_model = ClipboardTextArguments
    risk = RiskLevel.MEDIUM

    async def execute(self, arguments: ClipboardTextArguments) -> ToolResult:
        await asyncio.to_thread(ClipboardService.set_text, arguments.text)
        return ToolResult(success=True, tool=self.name, message=f"Set {len(arguments.text)} clipboard characters.")


def build_clipboard_tools() -> list[BaseTool]:
    return [GetClipboardTextTool(), SetClipboardTextTool()]
