import asyncio

import pytest

from tools.base import EmptyArguments
from tools.windows import VolumeUpTool, WindowService


class FakeVolume:
    def adjust(self, delta: int) -> int:
        assert delta == 5
        return 55


def test_window_resolution_rejects_ambiguity() -> None:
    service = WindowService()
    service.windows = lambda: [
        {"handle": 1, "title": "Notes A", "application": "notepad.exe", "pid": 1},
        {"handle": 2, "title": "Notes B", "application": "notepad.exe", "pid": 2},
    ]
    with pytest.raises(ValueError, match="ambiguous"):
        service.resolve("notepad")


def test_volume_tool_reports_actual_adjusted_value() -> None:
    result = asyncio.run(VolumeUpTool(FakeVolume()).execute(EmptyArguments()))
    assert result.success and result.data["percent"] == 55
