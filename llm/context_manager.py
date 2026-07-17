"""Bounded active conversation context for a 64K model window."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable

from assistant.models import ChatMessage
from llm.prompts import SYSTEM_PROMPT

Summarizer = Callable[[list[ChatMessage]], Awaitable[str]]


class ContextManager:
    """Keep recent turns and compact old history before the request budget is full."""

    def __init__(
        self,
        context_size: int = 65536,
        output_reserve: int = 4096,
        tool_reserve: int = 4096,
        system_prompt: str = SYSTEM_PROMPT,
    ) -> None:
        self.context_size = context_size
        self.output_reserve = output_reserve
        self.tool_reserve = tool_reserve
        self.system_prompt = system_prompt
        self.messages: list[ChatMessage] = []
        self.summary = ""
        self.preferences: dict[str, str] = {}

    @staticmethod
    def estimate_tokens(value: str | list[ChatMessage]) -> int:
        """Conservative tokenizer-free estimate suitable for admission control."""
        if isinstance(value, str):
            text = value
        else:
            text = json.dumps([item.to_ollama() for item in value], ensure_ascii=False)
        return max(1, (len(text.encode("utf-8")) + 2) // 3)

    @property
    def input_budget(self) -> int:
        return self.context_size - self.output_reserve - self.tool_reserve

    def add(self, message: ChatMessage) -> None:
        self.messages.append(message)

    def clear(self) -> None:
        self.messages.clear()
        self.summary = ""

    def prune_consumed_tool_data(self) -> None:
        """Keep outcomes but remove bulky data after the model has consumed it."""
        for index, message in enumerate(self.messages):
            if message.role != "tool" or len(message.content) < 1500:
                continue
            try:
                payload = json.loads(message.content)
                compact = {
                    "success": payload.get("success", False),
                    "tool": payload.get("tool", message.tool_name),
                    "message": payload.get("message", "Tool result consumed."),
                    "error": payload.get("error"),
                }
                self.messages[index] = ChatMessage(
                    role="tool", tool_name=message.tool_name, content=json.dumps(compact, ensure_ascii=False)
                )
            except (json.JSONDecodeError, TypeError):
                self.messages[index] = ChatMessage(
                    role="tool", tool_name=message.tool_name, content="Earlier tool result consumed."
                )

    def build(self) -> list[ChatMessage]:
        prefix = [ChatMessage(role="system", content=self.system_prompt)]
        if self.preferences:
            values = "\n".join(f"- {key}: {value}" for key, value in sorted(self.preferences.items()))
            prefix.append(ChatMessage(role="system", content=f"Approved user preferences:\n{values}"))
        if self.summary:
            prefix.append(ChatMessage(role="system", content=f"Older conversation summary:\n{self.summary}"))
        return prefix + self.messages

    def needs_compaction(self) -> bool:
        return self.estimate_tokens(self.build()) > self.input_budget

    async def compact(self, summarizer: Summarizer) -> None:
        """Summarize older turns while retaining the newest useful exchange."""
        if len(self.messages) < 6:
            raise ValueError("A single request exceeds the configured context budget")
        keep_count = min(8, max(2, len(self.messages) // 3))
        old, recent = self.messages[:-keep_count], self.messages[-keep_count:]
        summary = await summarizer(old)
        self.summary = "\n".join(part for part in (self.summary, summary.strip()) if part)
        self.messages = recent
        if self.needs_compaction():
            self.messages = self.messages[-4:]
