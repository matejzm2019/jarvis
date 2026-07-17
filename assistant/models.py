"""Shared validated runtime models."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ToolResult(BaseModel):
    """Stable result envelope returned by every tool."""

    model_config = ConfigDict(extra="forbid")
    success: bool
    tool: str
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class FunctionCall(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: Literal["function"] = "function"
    function: FunctionCall


class ChatMessage(BaseModel):
    """Ollama-compatible chat message."""

    model_config = ConfigDict(extra="ignore")
    role: Literal["system", "user", "assistant", "tool"]
    content: str = ""
    images: list[str] | None = None
    tool_calls: list[ToolCall] | None = None
    tool_name: str | None = None

    def to_ollama(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)


class ChatResponse(BaseModel):
    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    message: ChatMessage

