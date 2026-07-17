"""Typed tools for explicit local memory and alias management."""

from __future__ import annotations

import asyncio
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from assistant.models import RiskLevel, ToolResult
from config import JarvisConfig
from memory.storage import MemoryStore
from tools.base import BaseTool, EmptyArguments
from tools.files import PathPolicy


class FactArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    fact: str = Field(min_length=1, max_length=2000)


class ForgetArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    query: str = Field(min_length=1, max_length=500)


class PreferenceArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    key: str = Field(min_length=1, max_length=80)
    value: str = Field(min_length=1, max_length=500)


class AliasArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    alias: str = Field(min_length=1, max_length=80)
    target: str = Field(min_length=1, max_length=1024)


class _MemoryTool:
    risk = RiskLevel.MEDIUM

    def __init__(self, store: MemoryStore) -> None:
        super().__init__()
        self.store = store


class RememberFactTool(_MemoryTool, BaseTool[FactArguments]):
    name = "remember_fact"
    description = "Remember one non-sensitive fact only when the user explicitly asked Jarvis to remember it."
    argument_model = FactArguments

    async def execute(self, arguments: FactArguments) -> ToolResult:
        memory_id = await asyncio.to_thread(self.store.remember_fact, arguments.fact)
        return ToolResult(success=True, tool=self.name, message="I remembered that locally.", data={"id": memory_id})


class ListMemoriesTool(_MemoryTool, BaseTool[EmptyArguments]):
    name = "list_memories"
    description = "List locally stored approved facts, preferences, and aliases."
    argument_model = EmptyArguments
    risk = RiskLevel.LOW

    async def execute(self, arguments: EmptyArguments) -> ToolResult:
        facts, preferences, applications, folders = await asyncio.gather(
            asyncio.to_thread(self.store.facts),
            asyncio.to_thread(self.store.preferences),
            asyncio.to_thread(self.store.aliases, "application"),
            asyncio.to_thread(self.store.aliases, "folder"),
        )
        count = len(facts) + len(preferences) + len(applications) + len(folders)
        message = "Nemám uložené žiadne trvalé informácie." if not count else f"Mám uložených {count} položiek lokálnej pamäte."
        return ToolResult(
            success=True, tool=self.name, message=message,
            data={"facts": facts, "preferences": preferences, "application_aliases": applications, "folder_aliases": folders},
        )


class ForgetMemoryTool(_MemoryTool, BaseTool[ForgetArguments]):
    name = "forget_memory"
    description = "Forget approved remembered facts matching a user-supplied phrase."
    argument_model = ForgetArguments

    async def execute(self, arguments: ForgetArguments) -> ToolResult:
        count = await asyncio.to_thread(self.store.forget_fact, arguments.query)
        return ToolResult(success=True, tool=self.name, message=f"Forgot {count} matching memories.", data={"removed": count})


class SetPreferenceTool(_MemoryTool, BaseTool[PreferenceArguments]):
    name = "set_preference"
    description = "Persist one non-sensitive preference only after the user explicitly states it as a lasting preference."
    argument_model = PreferenceArguments

    async def execute(self, arguments: PreferenceArguments) -> ToolResult:
        await asyncio.to_thread(self.store.set_preference, arguments.key, arguments.value)
        return ToolResult(success=True, tool=self.name, message=f"Saved preference {arguments.key} locally.")


class ClearPreferencesTool(_MemoryTool, BaseTool[EmptyArguments]):
    name = "clear_preferences"
    description = "Delete all locally stored user preferences after an explicit user request."
    argument_model = EmptyArguments

    async def execute(self, arguments: EmptyArguments) -> ToolResult:
        count = await asyncio.to_thread(self.store.clear_preferences)
        return ToolResult(success=True, tool=self.name, message=f"Deleted {count} preferences.", data={"removed": count})


class ClearConversationHistoryTool(_MemoryTool, BaseTool[EmptyArguments]):
    name = "clear_conversation_history"
    description = "Delete the bounded local conversation history after an explicit user request."
    argument_model = EmptyArguments

    async def execute(self, arguments: EmptyArguments) -> ToolResult:
        count = await asyncio.to_thread(self.store.clear_history)
        return ToolResult(success=True, tool=self.name, message=f"Deleted {count} conversation messages.", data={"removed": count})


class SetApplicationAliasTool(_MemoryTool, BaseTool[AliasArguments]):
    name = "set_application_alias"
    description = "Map a user-confirmed alias to the name of an application already in the configured allowlist."
    argument_model = AliasArguments

    def __init__(self, store: MemoryStore, config: JarvisConfig) -> None:
        super().__init__(store)
        self.allowed = {item.name.casefold(): item.name for item in config.applications.allowlist}

    async def execute(self, arguments: AliasArguments) -> ToolResult:
        target = self.allowed.get(arguments.target.casefold())
        if not target:
            raise ValueError("Application alias target must exactly match an allowlisted application name")
        await asyncio.to_thread(self.store.set_alias, "application", arguments.alias, target)
        return ToolResult(success=True, tool=self.name, message=f"Saved application alias {arguments.alias} for {target}.")


class SetFolderAliasTool(_MemoryTool, BaseTool[AliasArguments]):
    name = "set_folder_alias"
    description = "Map a user-confirmed alias to an existing folder inside configured searchable directories."
    argument_model = AliasArguments

    def __init__(self, store: MemoryStore, config: JarvisConfig) -> None:
        super().__init__(store)
        self.policy = PathPolicy(config.searchable_paths())

    async def execute(self, arguments: AliasArguments) -> ToolResult:
        path = await asyncio.to_thread(self.policy.require, arguments.target, kind="folder")
        await asyncio.to_thread(self.store.set_alias, "folder", arguments.alias, str(path))
        return ToolResult(success=True, tool=self.name, message=f"Saved folder alias {arguments.alias}.", data={"path": str(path)})


def build_memory_tools(store: MemoryStore, config: JarvisConfig) -> list[BaseTool]:
    """Build the explicit persistent-memory tool set."""
    return [
        RememberFactTool(store), ListMemoriesTool(store), ForgetMemoryTool(store),
        SetPreferenceTool(store), ClearPreferencesTool(store), ClearConversationHistoryTool(store),
        SetApplicationAliasTool(store, config), SetFolderAliasTool(store, config),
    ]
