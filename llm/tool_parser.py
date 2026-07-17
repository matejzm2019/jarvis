"""Validation of untrusted model-generated tool calls."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from assistant.models import ToolCall
from tools.registry import ToolRegistry


class ToolParseError(ValueError):
    pass


def validate_tool_call(raw: ToolCall | dict[str, Any], registry: ToolRegistry) -> ToolCall:
    """Validate call shape, registry membership, and the exact argument schema."""
    try:
        call = raw if isinstance(raw, ToolCall) else ToolCall.model_validate(raw)
        tool = registry.get(call.function.name)
        tool.validate_arguments(call.function.arguments)
        return call
    except (KeyError, ValidationError, ValueError, TypeError) as exc:
        raise ToolParseError(str(exc)) from exc

