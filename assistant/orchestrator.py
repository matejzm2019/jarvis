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

_TOOL_HINTS: tuple[tuple[re.Pattern[str], set[str]], ...] = (
    (re.compile(r"(?i)\b(web|website|site|page|internet|online|search|google|youtube|news|latest|current|today|weather|download|gallery|screenshots?|stránk|strank|sekci|časť|cast|vyhľadaj|vyhladaj|vygoogli)\b"), {
        "open_website", "search_web_in_browser", "search_public_web", "read_public_webpage",
        "open_web_section", "search_youtube", "play_youtube", "open_browser", "focus_browser",
    }),
    (re.compile(r"(?i)\b(app|application|program|game|steam|process|launch|start|open|close|focus|switch|spusti|otvor|zavri|hra|hru|aplik|proces)\b"), {
        "open_application", "close_application", "focus_application", "list_running_applications",
        "find_installed_application", "get_foreground_application", "switch_window", "focus_window",
    }),
    (re.compile(r"(?i)(?:\b(file|folder|directory|document|download|recent|summari[sz]e|read|súbor|subor|priečinok|priecinok|adresár|adresar|dokument|zosumarizuj|zhrň|zhrn|prečítaj|precitaj)\b|[a-z]:\\|\.(txt|md|json|csv|log|py|js|ts|html|css|xml|ya?ml|pdf|docx)\b)"), {
        "search_files", "search_folders", "open_file", "open_folder", "list_folder",
        "read_text_file", "summarize_file", "find_recent_files", "get_file_information",
        "find_file_by_partial_name",
    }),
    (re.compile(r"(?i)\b(screen|visible|screenshot|window|button|error|obrazovk|vidíš|vidis|okno|tlačid|tlacid|chyba)\b"), {
        "capture_screen", "capture_active_window", "describe_screen", "summarize_visible_content",
        "locate_visible_ui_element", "read_visible_error_message", "get_active_window",
        "minimize_window", "maximize_window", "restore_window", "close_window", "switch_window", "focus_window",
    }),
    (re.compile(r"(?i)\b(music|song|track|video|media|spotify|volume|sound|hudb|skladb|zvuk|hlasitosť|hlasitost)\b"), {
        "play_music", "pause_music", "resume_music", "stop_music", "next_track", "previous_track",
        "get_current_track", "set_media_volume", "search_local_music", "play_local_audio_file",
        "set_volume", "volume_up", "volume_down", "mute_volume", "unmute_volume", "play_youtube", "search_youtube",
    }),
    (re.compile(r"(?i)\b(cpu|gpu|ram|memory|disk|battery|network|bluetooth|uptime|system|time|procesor|pamäť|pamat|disk|batéri|bateri|sieť|siet|čas|cas|hodín|hodin)\b"), {
        "get_cpu_usage", "get_gpu_information", "get_memory_usage", "get_disk_usage", "get_battery_status",
        "get_network_status", "get_connected_bluetooth_devices", "get_current_time", "get_system_uptime",
    }),
    (re.compile(r"(?i)\b(type|write|press|key|hotkey|click|mouse|scroll|clipboard|napíš|napis|stlač|stlac|klik|roluj|schránk)\b"), {
        "type_text", "press_key", "press_hotkey", "click_screen_position", "scroll",
        "get_clipboard_text", "set_clipboard_text",
    }),
    (re.compile(r"(?i)\b(remember|forget|preference|alias|history|pamät|pamat|zabudni|preferenc|históri|histori)\b"), {
        "remember_fact", "list_memories", "forget_memory", "set_preference", "clear_preferences",
        "clear_conversation_history", "set_application_alias", "set_folder_alias",
    }),
)


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
        self.context = ContextManager(
            context_size=config.ollama.context_size,
            output_reserve=config.ollama.max_output_tokens,
        )
        self.context.preferences = self.memory.preferences()
        self.context.messages = restore_messages(self.memory, config.memory.restore_recent_messages)
        self.conversation = Conversation(self.context, self.memory)
        service = confirmation_service or ConsoleConfirmationService()
        self.permissions = PermissionManager(config.permissions, service)
        self.router = IntentRouter()
        self.state = AssistantState()
        self.log = logging.getLogger("jarvis.orchestrator")
        self._active_request = ""

    def _relevant_tool_names(self, request: str) -> set[str]:
        """Keep Ollama prompts small by exposing only tools relevant to this request."""
        selected: set[str] = set()
        for pattern, names in _TOOL_HINTS:
            if pattern.search(request):
                selected.update(names)
        return selected & self.registry.names

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
            "search_youtube": r"\b(youtube|video|vyhľadaj|vyhladaj|nájdi|najdi)\b",
            "play_youtube": r"\b(youtube|video|play|pusti|prehraj)\b",
            "open_web_section": r"\b(web|website|site|page|section|search|find|stránk|strank|sekci|časť|cast|vyhľadaj|vyhladaj|nájdi|najdi)\b",
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
        for key in ("text", "query", "site", "section"):
            if key in permission_arguments and tool.name in {
                "type_text", "set_clipboard_text", "search_web_in_browser",
                "search_public_web", "search_youtube", "play_youtube", "open_web_section",
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
        if result.tool == "open_web_section":
            return result.message
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
        web_results = result.data.get("results")
        if isinstance(web_results, list):
            items = [
                f"{item.get('title')}: {item.get('url')}"
                for item in web_results[:5] if isinstance(item, dict)
            ]
            return result.message if not items else f"{result.message} " + " | ".join(items)
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
        tool_schemas = self.registry.schemas(self._relevant_tool_names(request))
        for _ in range(4):
            if self.context.needs_compaction():
                await self.context.compact(self._summarize)
            response = await self.client.chat(
                self.context.build(),
                tool_schemas,
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
