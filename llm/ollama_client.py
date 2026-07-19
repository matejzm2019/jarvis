"""Reusable asynchronous client for the local Ollama HTTP API."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx

from assistant.models import ChatMessage, ChatResponse, ToolCall
from config import OllamaConfig


class OllamaError(RuntimeError):
    """Human-readable local Ollama failure."""


class OllamaUnavailableError(OllamaError):
    pass


class ModelUnavailableError(OllamaError):
    pass


class OllamaClient:
    """Async, cancellable Ollama client with bounded retries and streaming."""

    def __init__(self, config: OllamaConfig, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.config = config
        self.base_url = str(config.base_url).rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(config.timeout_seconds),
            transport=transport,
        )

    async def __aenter__(self) -> "OllamaClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        for attempt in range(self.config.retries + 1):
            try:
                response = await self._client.request(method, path, **kwargs)
                response.raise_for_status()
                return response
            except asyncio.CancelledError:
                raise
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                if attempt >= self.config.retries:
                    raise OllamaUnavailableError(
                        f"Cannot connect to local Ollama at {self.base_url}: {exc}"
                    ) from exc
                await asyncio.sleep(0.3 * (2**attempt))
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code >= 500 and attempt < self.config.retries:
                    await asyncio.sleep(0.3 * (2**attempt))
                    continue
                detail = exc.response.text[:500]
                raise OllamaError(f"Ollama HTTP {exc.response.status_code}: {detail}") from exc
        raise OllamaUnavailableError(f"Cannot connect to local Ollama at {self.base_url}")

    async def health_check(self) -> dict[str, Any]:
        """Check the server and configured model without pulling anything."""
        version = (await self._request("GET", "/api/version")).json()
        tags = (await self._request("GET", "/api/tags")).json()
        names = {str(item.get("name", "")).split(":", 1)[0] for item in tags.get("models", [])}
        configured = self.config.model.split(":", 1)[0]
        if configured not in names:
            raise ModelUnavailableError(
                f"Local model '{self.config.model}' is unavailable. Check installed models with: ollama list"
            )
        return {"version": version.get("version", "unknown"), "model": self.config.model}

    def _payload(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None,
        stream: bool,
        format_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [message.to_ollama() for message in messages],
            "stream": stream,
            "keep_alive": self.config.keep_alive,
            "options": {
                "temperature": self.config.temperature,
                "num_ctx": self.config.context_size,
                "num_predict": self.config.max_output_tokens,
            },
        }
        if tools:
            payload["tools"] = tools
        if format_schema:
            payload["format"] = format_schema
        return payload

    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
        *,
        stream: bool = True,
        on_token: Callable[[str], None] | None = None,
        format_schema: dict[str, Any] | None = None,
    ) -> ChatResponse:
        """Chat locally, accumulating content and structured tool calls."""
        if not stream:
            response = await self._request(
                "POST", "/api/chat", json=self._payload(messages, tools, False, format_schema)
            )
            return self._parse_message(response.json().get("message", {}))

        for attempt in range(self.config.retries + 1):
            content_parts: list[str] = []
            tool_calls: list[ToolCall] = []
            try:
                async with self._client.stream(
                    "POST", "/api/chat", json=self._payload(messages, tools, True, format_schema)
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        chunk = json.loads(line)
                        if chunk.get("error"):
                            raise OllamaError(str(chunk["error"]))
                        raw_message = chunk.get("message", {})
                        token = str(raw_message.get("content", ""))
                        if token:
                            content_parts.append(token)
                            if on_token:
                                on_token(token)
                        for raw_call in raw_message.get("tool_calls") or []:
                            tool_calls.append(ToolCall.model_validate(raw_call))
                message = ChatMessage(
                    role="assistant", content="".join(content_parts), tool_calls=tool_calls or None
                )
                return ChatResponse(content=message.content, tool_calls=tool_calls, message=message)
            except asyncio.CancelledError:
                raise
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                if attempt >= self.config.retries or content_parts:
                    raise OllamaUnavailableError(
                        f"Cannot connect to local Ollama at {self.base_url}: {exc}"
                    ) from exc
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code < 500 or attempt >= self.config.retries:
                    raise OllamaError(
                        f"Ollama HTTP {exc.response.status_code}: {exc.response.text[:500]}"
                    ) from exc
            await asyncio.sleep(0.3 * (2**attempt))
        raise OllamaUnavailableError(f"Cannot connect to local Ollama at {self.base_url}")

    @staticmethod
    def _parse_message(raw: dict[str, Any]) -> ChatResponse:
        message = ChatMessage.model_validate({"role": "assistant", **raw})
        return ChatResponse(
            content=message.content,
            tool_calls=message.tool_calls or [],
            message=message,
        )
