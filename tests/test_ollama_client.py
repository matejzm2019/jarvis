import asyncio
import json

import httpx
import pytest

from assistant.models import ChatMessage
from config import OllamaConfig
from llm.ollama_client import ModelUnavailableError, OllamaClient


def transport_with_models(models: list[str]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "test"})
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": name} for name in models]})
        if request.url.path == "/api/chat":
            payload = json.loads(request.content)
            assert payload["model"] == "gemma64"
            assert payload["options"]["num_ctx"] == 65536
            assert payload["options"]["num_predict"] == 768
            if payload["stream"]:
                content = b'{"message":{"role":"assistant","content":"Hello"},"done":true}\n'
                return httpx.Response(200, content=content)
            return httpx.Response(200, json={"message": {"role": "assistant", "content": "Hello"}})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_health_check_accepts_tagged_model() -> None:
    async def run() -> None:
        async with OllamaClient(OllamaConfig(), transport_with_models(["gemma64:latest"])) as client:
            result = await client.health_check()
            assert result == {"version": "test", "model": "gemma64"}

    asyncio.run(run())


def test_health_check_rejects_missing_model() -> None:
    async def run() -> None:
        async with OllamaClient(OllamaConfig(), transport_with_models(["other:latest"])) as client:
            with pytest.raises(ModelUnavailableError, match="ollama list"):
                await client.health_check()

    asyncio.run(run())


def test_streaming_chat_accumulates_content() -> None:
    async def run() -> None:
        async with OllamaClient(OllamaConfig(), transport_with_models(["gemma64"])) as client:
            response = await client.chat([ChatMessage(role="user", content="Hi")])
            assert response.content == "Hello"

    asyncio.run(run())


def test_image_and_json_schema_are_sent_to_ollama() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen.update(payload)
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "{}"}})

    async def run() -> None:
        async with OllamaClient(OllamaConfig(), httpx.MockTransport(handler)) as client:
            await client.chat(
                [ChatMessage(role="user", content="inspect", images=["aW1hZ2U="])],
                stream=False,
                format_schema={"type": "object"},
            )

    asyncio.run(run())
    assert seen["messages"][0]["images"] == ["aW1hZ2U="]
    assert seen["format"] == {"type": "object"}
