"""Jarvis local agent loop and deterministic command routing."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from pathlib import Path

from assistant.confirmation import ConsoleConfirmationService, ConfirmationService
from assistant.conversation import Conversation
from assistant.intent_router import IntentRouter
from assistant.models import ChatMessage, ToolCall, ToolResult
from assistant.permissions import PermissionManager
from assistant.state import AssistantState, AssistantStatus
from config import JarvisConfig
from llm.context_manager import ContextManager
from llm.ollama_client import OllamaClient
from llm.prompts import SUMMARY_PROMPT
from llm.tool_parser import ToolParseError, validate_tool_call
from memory.short_term import restore_messages
from memory.storage import MemoryStore
from tools.registry import ToolRegistry, build_default_registry
from utils.paths import PROJECT_ROOT


class JarvisOrchestrator:
    """Coordinate context, local model tool selection, permissions, and execution."""

    def __init__(
        self,
        config: JarvisConfig,
        client: OllamaClient,
        registry: ToolRegistry | None = None,
        confirmation_service: ConfirmationService | None = None,
    ) -> None:
        self.config = config
        self.client = client
        configured_database = Path(config.memory.database_path)
        database_path = configured_database if configured_database.is_absolute() else PROJECT_ROOT / configured_database
        self.memory = MemoryStore(database_path, config.memory.max_history_messages)
        self.registry = registry or build_default_registry(config, client, self.memory)
        self.context = ContextManager(context_size=config.ollama.context_size)
        self.context.preferences = self.memory.preferences()
        self.context.messages = restore_messages(self.memory, config.memory.restore_recent_messages)
        self.conversation = Conversation(self.context, self.memory)
        service = confirmation_service or ConsoleConfirmationService()
        self.permissions = PermissionManager(config.permissions, service)
        self.router = IntentRouter()
        self.state = AssistantState()
        self.log = logging.getLogger("jarvis.orchestrator")
        self._active_request = ""

    @staticmethod
    def _explicit_tool_request(tool_name: str, request: str) -> bool:
        patterns = {
            "remember_fact": r"\b(remember|zapamätaj|pamätaj|ulož si)\b",
            "set_preference": r"\b(preferujem|odteraz|nastav|remember my preference|my preference)\b",
            "set_application_alias": r"\b(alias|prezýv|volaj|nazývaj)\b",
            "set_folder_alias": r"\b(alias|prezýv|volaj|nazývaj)\b",
            "forget_memory": r"\b(forget|zabudni)\b",
            "clear_preferences": r"\b(clear|delete|vymaž|zruš).*(preference|preferenc)\b",
            "clear_conversation_history": r"\b(clear|delete|vymaž).*(history|históri)\b",
            "get_clipboard_text": r"\b(clipboard|schránk)\b",
            "set_clipboard_text": r"\b(copy|clipboard|skopíruj|schránk)\b",
            "type_text": r"\b(type|write|napíš|napis|zadaj)\b",
            "press_key": r"\b(press|stlač|stlac)\b",
            "press_hotkey": r"\b(hotkey|shortcut|press|skratk|stlač|stlac)\b",
            "click_screen_position": r"\b(click|klik)\b",
            "scroll": r"\b(scroll|posuň|roluj)\b",
            "search_web_in_browser": r"\b(search|google|web|internet|vyhľadaj|hladaj)\b",
            "open_website": r"\b(open|otvor|website|stránk|web)\b",
            "lock_computer": r"\b(lock|zamkni|uzamkni)\b",
        }
        pattern = patterns.get(tool_name)
        return not pattern or bool(re.search(pattern, request, re.IGNORECASE))

    async def _summarize(self, messages: list[ChatMessage]) -> str:
        transcript = "\n".join(f"{item.role}: {item.content}" for item in messages)
        response = await self.client.chat(
            [
                ChatMessage(role="system", content=SUMMARY_PROMPT),
                ChatMessage(role="user", content=transcript),
            ],
            stream=False,
        )
        return response.content

    async def _execute_call(self, call: ToolCall) -> ToolResult:
        tool = self.registry.get(call.function.name)
        sensitive_input = re.search(
            r"(?i)\b(password|passphrase|heslo|api[ _-]?key|access[ _-]?token|private[ _-]?key)\b",
            self._active_request,
        )
        sensitive_click = re.search(
            r"(?i)\b(purchase|buy|pay|submit|send|confirm|delete|install|security warning|kúpiť|zaplatiť|odoslať|potvrdiť|vymazať|inštalovať)\b",
            self._active_request,
        )
        if tool.name in {"type_text", "set_clipboard_text"} and sensitive_input:
            return ToolResult(
                success=False, tool=tool.name,
                message="Typing or copying passwords, keys, and tokens is forbidden.",
                error="Sensitive input rejected",
            )
        if tool.name == "click_screen_position" and sensitive_click:
            return ToolResult(
                success=False, tool=tool.name,
                message="Sensitive purchase, submit, delete, install, or security-warning clicks are not implemented.",
                error="Sensitive click rejected",
            )
        if not self._explicit_tool_request(tool.name, self._active_request):
            return ToolResult(
                success=False, tool=tool.name,
                message="This action requires an explicit user request.",
                error="Explicit user intent was not detected",
            )
        permission_arguments = dict(call.function.arguments)
        for key in ("text", "query"):
            if key in permission_arguments and tool.name in {
                "type_text", "set_clipboard_text", "search_web_in_browser"
            }:
                permission_arguments[key] = f"<{len(str(permission_arguments[key]))} characters>"
        description = f"{tool.description} Arguments: {json.dumps(permission_arguments, ensure_ascii=False)}"
        if not await self.permissions.authorize(tool.risk, description):
            return ToolResult(
                success=False,
                tool=tool.name,
                message="Action was not authorized.",
                error="Permission denied",
            )
        self.state.set(AssistantStatus.EXECUTING)
        result = await tool.invoke(call.function.arguments)
        if result.success and tool.name in {"set_preference", "clear_preferences"}:
            self.context.preferences = self.memory.preferences()
        if result.success and tool.name == "clear_conversation_history":
            self.context.clear()
        return result

    @staticmethod
    def _direct_result(result: ToolResult) -> str:
        if not result.success:
            return f"{result.message} {result.error or ''}".strip()
        if result.tool == "list_memories":
            parts: list[str] = []
            facts = result.data.get("facts", [])
            parts.extend(str(item.get("fact")) for item in facts if isinstance(item, dict))
            preferences = result.data.get("preferences", {})
            if isinstance(preferences, dict):
                parts.extend(f"{key}: {value}" for key, value in preferences.items())
            for key in ("application_aliases", "folder_aliases"):
                aliases = result.data.get(key, {})
                if isinstance(aliases, dict):
                    parts.extend(f"{alias} → {target}" for alias, target in aliases.items())
            return "Nemám uložené žiadne trvalé informácie." if not parts else "Pamätám si: " + "; ".join(parts)
        apps = result.data.get("applications")
        if isinstance(apps, list):
            names = [str(item.get("name", "")) for item in apps[:25] if isinstance(item, dict)]
            return f"{result.message} " + ", ".join(names)
        title = result.data.get("title")
        application = result.data.get("application")
        if title or application:
            return f"{application or 'Application'} — {title or 'untitled window'}"
        return result.message

    async def ask(self, text: str, on_token: Callable[[str], None] | None = None) -> str:
        """Handle one text request; cancellation propagates to HTTP and tools."""
        request = text.strip()
        if not request:
            return ""
        self._active_request = request
        sensitive_result_used = False
        routed = self.router.route(request, self.registry.names)
        if isinstance(routed, str):
            return routed
        self.conversation.add_user(request)
        if isinstance(routed, ToolCall):
            result = await self._execute_call(routed)
            answer = self._direct_result(result)
            if result.tool != "clear_conversation_history":
                self.conversation.add_assistant(
                    answer,
                    persist=result.tool not in {
                        "get_clipboard_text", "read_text_file", "summarize_file",
                        "describe_screen", "summarize_visible_content", "read_visible_error_message",
                    },
                )
            self.state.set(AssistantStatus.SLEEPING)
            return answer

        self.state.set(AssistantStatus.THINKING)
        for _ in range(4):
            if self.context.needs_compaction():
                await self.context.compact(self._summarize)
            response = await self.client.chat(
                self.context.build(),
                self.registry.schemas(),
                stream=True,
                on_token=on_token,
            )
            self.context.add(response.message)
            if not response.tool_calls:
                answer = response.content.strip() or "I could not produce a response."
                if not sensitive_result_used:
                    self.memory.add_message("assistant", answer)
                self.context.prune_consumed_tool_data()
                self.state.set(AssistantStatus.SLEEPING)
                return answer
            for raw_call in response.tool_calls:
                try:
                    call = validate_tool_call(raw_call, self.registry)
                    result = await self._execute_call(call)
                    sensitive_result_used |= result.tool in {
                        "get_clipboard_text", "read_text_file", "summarize_file",
                        "describe_screen", "summarize_visible_content", "read_visible_error_message",
                    }
                except ToolParseError as exc:
                    result = ToolResult(
                        success=False,
                        tool=raw_call.function.name,
                        message="The requested tool call was rejected.",
                        error=str(exc),
                    )
                self.context.add(
                    ChatMessage(
                        role="tool",
                        tool_name=result.tool,
                        content=result.model_dump_json(),
                    )
                )
            self.state.set(AssistantStatus.THINKING)
        self.state.set(AssistantStatus.ERROR)
        return "I stopped because the request exceeded the safe tool-step limit."
