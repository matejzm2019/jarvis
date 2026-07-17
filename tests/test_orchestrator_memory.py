import asyncio

from assistant.models import ChatMessage, ChatResponse
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
