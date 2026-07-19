import asyncio

from pydantic import BaseModel, ConfigDict

from assistant.models import ToolResult
from config import JarvisConfig, MemoryConfig
from memory.storage import MemoryStore
from tools.base import BaseTool
from tools.registry import ToolRegistry, build_default_registry


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: int


class EchoTool(BaseTool[Args]):
    name = "echo"
    description = "Echo a validated integer."
    argument_model = Args

    async def execute(self, arguments: Args) -> ToolResult:
        return ToolResult(success=True, tool=self.name, message="ok", data={"value": arguments.value})


class FailingTool(EchoTool):
    name = "fail"

    async def execute(self, arguments: Args) -> ToolResult:
        raise RuntimeError("expected")


def test_registry_rejects_duplicate_names() -> None:
    registry = ToolRegistry([EchoTool()])
    try:
        registry.register(EchoTool())
    except ValueError as exc:
        assert "Duplicate" in str(exc)
    else:
        raise AssertionError("duplicate tool was accepted")


def test_tool_rejects_extra_model_arguments() -> None:
    result = asyncio.run(EchoTool().invoke({"value": 3, "unexpected": True}))
    assert not result.success
    assert result.error


def test_schema_exposes_pydantic_contract() -> None:
    schema = EchoTool().schema()
    assert schema["function"]["name"] == "echo"
    assert schema["function"]["parameters"]["required"] == ["value"]


def test_expected_tool_failure_has_no_stack_trace_without_debug(caplog) -> None:
    result = asyncio.run(FailingTool().invoke({"value": 1}))
    assert not result.success
    assert all(record.exc_info is None for record in caplog.records)


def test_phase5_registry_contains_media_music_and_memory_tools(tmp_path) -> None:
    config = JarvisConfig(memory=MemoryConfig(database_path=str(tmp_path / "memory.db")))
    store = MemoryStore(tmp_path / "memory.db")
    registry = build_default_registry(config, object(), store)
    assert {
        "play_music", "pause_music", "resume_music", "stop_music", "next_track",
        "previous_track", "get_current_track", "set_media_volume", "search_local_music",
        "play_local_audio_file", "remember_fact", "list_memories",
    } <= registry.names


def test_registry_contains_all_requested_safe_desktop_tools(tmp_path) -> None:
    config = JarvisConfig(memory=MemoryConfig(database_path=str(tmp_path / "memory.db")))
    registry = build_default_registry(config, object(), MemoryStore(tmp_path / "memory.db"))
    assert {
        "close_application", "minimize_window", "maximize_window", "restore_window",
        "close_window", "switch_window", "focus_window", "set_volume", "volume_up",
        "volume_down", "mute_volume", "lock_computer", "show_desktop", "type_text",
        "press_key", "press_hotkey", "click_screen_position", "scroll",
        "get_clipboard_text", "set_clipboard_text", "open_website",
        "search_web_in_browser", "open_browser", "focus_browser",
        "search_public_web", "read_public_webpage", "search_youtube", "play_youtube",
        "get_connected_bluetooth_devices", "unmute_volume",
    } <= registry.names
