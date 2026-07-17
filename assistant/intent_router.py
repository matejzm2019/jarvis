"""Fast deterministic routing for simple, unambiguous commands."""

from __future__ import annotations

import re

from assistant.models import FunctionCall, ToolCall


class IntentRouter:
    """Route exact commands without spending an LLM tool-selection request."""

    _routes: tuple[tuple[re.Pattern[str], str, dict[str, str]], ...] = (
        (re.compile(r"^(list|show) (running )?(apps|applications)$", re.I), "list_running_applications", {}),
        (re.compile(r"^(what('| i)s|show|get) (the )?(active|foreground) window$", re.I), "get_active_window", {}),
        (re.compile(r"^(show|get|what('| i)s) (the )?cpu( usage)?$", re.I), "get_cpu_usage", {}),
        (re.compile(r"^(show|get|what('| i)s) (the )?(memory|ram)( usage)?$", re.I), "get_memory_usage", {}),
        (re.compile(r"^(koľko|aka|aká).*(ram|pamäť)", re.I), "get_memory_usage", {}),
        (re.compile(r"^(pause|pause music|pozastav hudbu)$", re.I), "pause_music", {}),
        (re.compile(r"^(resume|resume music|pokračuj v hudbe)$", re.I), "resume_music", {}),
        (re.compile(r"^(next|next song|next track|ďalšia skladba|ďalšiu skladbu)$", re.I), "next_track", {}),
        (re.compile(r"^(previous|previous song|previous track|predošlá skladba|predošlú skladbu)$", re.I), "previous_track", {}),
        (re.compile(r"^(stop music|zastav hudbu)$", re.I), "stop_music", {}),
        (re.compile(r"^(what is playing|current track|čo hrá|čo práve hrá)$", re.I), "get_current_track", {}),
        (re.compile(r"^(what do you remember about me|čo si o mne pamätáš)[?.!]*$", re.I), "list_memories", {}),
        (re.compile(r"^(clear|delete|vymaž) (the )?(conversation )?(history|históriu konverzácie)[?.!]*$", re.I), "clear_conversation_history", {}),
        (re.compile(r"^(clear|delete|vymaž) (all )?(preferences|všetky preferencie)[?.!]*$", re.I), "clear_preferences", {}),
        (re.compile(r"^(zobraz|ukáž).*(proces|aplik)", re.I), "list_running_applications", {}),
        (re.compile(r"^(what do you see|describe what is visible)( on (the )?screen)?[?.!]*$", re.I), "describe_screen", {}),
        (re.compile(r"^čo vidíš( na obrazovke)?[?.!]*$", re.I), "describe_screen", {"focus": "Odpovedz po slovensky."}),
        (re.compile(r"^(summarize|describe) (this|the active) (window|application)[?.!]*$", re.I), "summarize_visible_content", {"scope": "active_window"}),
        (re.compile(r"^(zosumarizuj|opíš)( mi)? (toto okno|túto aplikáciu)[?.!]*$", re.I), "summarize_visible_content", {"scope": "active_window", "focus": "Odpovedz po slovensky."}),
        (re.compile(r"^(what does|what is) (this|the visible) error( mean)?[?.!]*$", re.I), "read_visible_error_message", {"scope": "active_window"}),
        (re.compile(r"^čo znamená (táto|viditeľná) chyba[?.!]*$", re.I), "read_visible_error_message", {"scope": "active_window", "focus": "Odpovedz po slovensky."}),
    )
    _cancel = {"cancel", "stop", "stop speaking", "prestaň", "ticho", "zruš"}

    def route(self, text: str, available_tools: set[str]) -> ToolCall | str | None:
        normalized = " ".join(text.strip().split())
        if normalized.casefold() in self._cancel:
            return "Cancelled."
        for pattern, tool_name, arguments in self._routes:
            if tool_name in available_tools and pattern.search(normalized):
                return ToolCall(function=FunctionCall(name=tool_name, arguments=dict(arguments)))
        return None
