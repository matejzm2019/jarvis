"""Typed base class for safe predefined tools."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any, ClassVar, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, ValidationError

from assistant.models import RiskLevel, ToolResult

ArgsT = TypeVar("ArgsT", bound=BaseModel)


class EmptyArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BaseTool(ABC, Generic[ArgsT]):
    """Validate, time-limit, log, and execute one predefined operation."""

    name: ClassVar[str]
    description: ClassVar[str]
    argument_model: ClassVar[type[BaseModel]]
    result_model: ClassVar[type[ToolResult]] = ToolResult
    risk: ClassVar[RiskLevel] = RiskLevel.LOW
    timeout_seconds: ClassVar[float] = 15
    permission_requirements: ClassVar[tuple[str, ...]] = ()

    def __init__(self) -> None:
        self.log = logging.getLogger(f"jarvis.tools.{self.name}")

    def schema(self) -> dict[str, Any]:
        """Return an Ollama-compatible function schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.argument_model.model_json_schema(),
            },
        }

    def validate_arguments(self, raw: dict[str, Any]) -> BaseModel:
        return self.argument_model.model_validate(raw)

    async def invoke(self, raw: dict[str, Any]) -> ToolResult:
        """Execute validated arguments and convert all failures to a stable envelope."""
        try:
            args = self.validate_arguments(raw)
        except ValidationError as exc:
            return ToolResult(
                success=False,
                tool=self.name,
                message="Tool arguments were rejected.",
                error=str(exc),
            )
        self.log.info("Executing tool=%s risk=%s", self.name, self.risk.value)
        try:
            result = await asyncio.wait_for(self.execute(args), timeout=self.timeout_seconds)
            validated = self.result_model.model_validate(result)
            self.log.info("Finished tool=%s success=%s", self.name, validated.success)
            return validated
        except asyncio.CancelledError:
            self.log.info("Cancelled tool=%s", self.name)
            raise
        except TimeoutError:
            self.log.warning("Timed out tool=%s", self.name)
            return ToolResult(
                success=False,
                tool=self.name,
                message="The operation timed out.",
                error=f"Timeout after {self.timeout_seconds:g} seconds",
            )
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            if self.log.isEnabledFor(logging.DEBUG):
                self.log.exception("Tool failed tool=%s", self.name)
            else:
                self.log.error("Tool failed tool=%s error=%s", self.name, error)
            return ToolResult(
                success=False,
                tool=self.name,
                message="The operation failed safely.",
                error=error,
            )

    @abstractmethod
    async def execute(self, arguments: ArgsT) -> ToolResult:
        """Perform the predefined operation."""
