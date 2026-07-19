import asyncio
from types import SimpleNamespace

from assistant.models import ChatMessage, ChatResponse, ToolResult
from assistant.orchestrator import JarvisOrchestrator
from config import JarvisConfig, MemoryConfig
from tools.registry import ToolRegistry


class FakeClient:
    async def chat(self, messages, tools=None, *, stream=True, on_token=None):
        message = ChatMessage(role="assistant", content="Ahoj.")
        return ChatResponse(content="Ahoj.", message=message)


def test_normal_model_turn_is_persisted_in_bounded_history(tmp_path) -> None:
    config = JarvisConfig(memory=MemoryConfig(database_path=str(tmp_path / "memory.db")))
    assistant = JarvisOrchestrator(config, FakeClient(), ToolRegistry())
    assert asyncio.run(assistant.ask("Ahoj")) == "Ahoj."
    assert [(item["role"], item["content"]) for item in assistant.memory.recent_messages(10)] == [
        ("user", "Ahoj"), ("assistant", "Ahoj."),
    ]


def test_request_relevant_tool_filter_reduces_ollama_schema_payload() -> None:
    assistant = object.__new__(JarvisOrchestrator)
    assistant.registry = SimpleNamespace(names={
        "search_public_web", "read_public_webpage", "open_application", "search_files",
    })
    assert assistant._relevant_tool_names("What is the latest Python version online?") == {
        "search_public_web", "read_public_webpage",
    }
    assert assistant._relevant_tool_names("Explain recursion") == set()


def test_open_web_section_uses_its_human_result_message() -> None:
    result = ToolResult(
        success=True,
        tool="open_web_section",
        message="Opened My Forza for section screenshots.",
        data={"title": "My Forza | Forza", "url": "https://forza.net/myforza"},
    )
    assert JarvisOrchestrator._direct_result(result) == result.message
