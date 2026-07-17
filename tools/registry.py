"""Typed tool registration and runtime composition."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from config import JarvisConfig
from tools.applications import (
    ApplicationCatalog,
    CloseApplicationTool,
    FindInstalledApplicationTool,
    FocusApplicationTool,
    GetForegroundApplicationTool,
    ListRunningApplicationsTool,
    OpenApplicationTool,
)
from tools.base import BaseTool
from tools.browser import build_browser_tools
from tools.clipboard import build_clipboard_tools
from tools.files import build_file_tools
from tools.keyboard_mouse import build_input_tools
from tools.media_controls import build_media_tools
from tools.memory_tools import build_memory_tools
from tools.music import build_music_tools
from tools.system_info import build_system_tools
from tools.windows import build_window_tools
from tools.vision_tools import build_vision_tools
from vision.screen_analyzer import ScreenAnalyzer
from memory.storage import MemoryStore


class ToolRegistry:
    """Unique allowlist of tools exposed to the model."""

    def __init__(self, tools: Iterable[BaseTool[Any]] = ()) -> None:
        self._tools: dict[str, BaseTool[Any]] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: BaseTool[Any]) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool[Any]:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"Unknown or unavailable tool: {name}") from exc

    @property
    def names(self) -> set[str]:
        return set(self._tools)

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.schema() for tool in self._tools.values()]


def build_phase1_registry(config: JarvisConfig, memory: MemoryStore | None = None) -> ToolRegistry:
    """Build only the tools implemented and tested for Phase 1."""
    aliases = (lambda: memory.aliases("application")) if memory else None
    catalog = ApplicationCatalog(config.applications, aliases)
    tools: list[BaseTool[Any]] = [
        OpenApplicationTool(catalog),
        CloseApplicationTool(catalog),
        FocusApplicationTool(catalog),
        ListRunningApplicationsTool(catalog),
        FindInstalledApplicationTool(catalog),
        GetForegroundApplicationTool(catalog),
    ]
    tools.extend(build_window_tools())
    tools.extend(build_browser_tools(catalog, config.browser))
    tools.extend(build_input_tools())
    tools.extend(build_clipboard_tools())
    tools.extend(build_file_tools(config, memory))
    tools.extend(build_system_tools())
    return ToolRegistry(tools)


def build_default_registry(config: JarvisConfig, client: Any, memory: MemoryStore | None = None) -> ToolRegistry:
    """Build the implemented local Phase 1 through Phase 5 tool set."""
    registry = build_phase1_registry(config, memory)
    for tool in build_vision_tools(ScreenAnalyzer(config.vision, client)):
        registry.register(tool)
    for tool in (*build_media_tools(config), *build_music_tools(config)):
        registry.register(tool)
    if memory:
        for tool in build_memory_tools(memory, config):
            registry.register(tool)
    return registry
