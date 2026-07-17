import asyncio

from config import JarvisConfig
from tools.registry import build_default_registry
from tools.vision_tools import DescribeScreenTool
from vision.screen_analyzer import AnalysisResult


class FakeAnalyzer:
    async def analyze(self, task: str, scope: str) -> AnalysisResult:
        return AnalysisResult("visible", {"source": scope})


def test_default_registry_includes_all_vision_tools() -> None:
    registry = build_default_registry(JarvisConfig(), object())
    expected = {
        "capture_screen", "capture_active_window", "describe_screen",
        "summarize_visible_content", "locate_visible_ui_element", "read_visible_error_message",
    }
    assert expected <= registry.names


def test_vision_tool_validates_arguments() -> None:
    tool = DescribeScreenTool(FakeAnalyzer())
    result = asyncio.run(tool.invoke({"scope": "screen", "unexpected": True}))
    assert not result.success
    assert result.error
