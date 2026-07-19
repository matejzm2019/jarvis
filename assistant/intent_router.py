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
        (re.compile(r"^(what time is it|what('| i)s the (current )?time|current time)[?.!]*$", re.I), "get_current_time", {}),
        (re.compile(r"^((koľko|kolko) je( teraz)? (hodín|hodin)|(aký|aky) je( teraz)? (čas|cas))[?.!]*$", re.I), "get_current_time", {}),
        (re.compile(r"^(pause|pause (music|video)|pozastav (hudbu|video))$", re.I), "pause_music", {}),
        (re.compile(r"^(resume|resume (music|video)|pokračuj (v hudbe|vo videu)|pokracuj (v hudbe|vo videu))$", re.I), "resume_music", {}),
        (re.compile(r"^(next|next song|next track|ďalšia skladba|ďalšiu skladbu)$", re.I), "next_track", {}),
        (re.compile(r"^(previous|previous song|previous track|predošlá skladba|predošlú skladbu)$", re.I), "previous_track", {}),
        (re.compile(r"^(stop (music|video)|zastav (hudbu|video))$", re.I), "stop_music", {}),
        (re.compile(r"^(mute|mute (sound|volume)|stlm zvuk|vypni zvuk)$", re.I), "mute_volume", {}),
        (re.compile(r"^(unmute|unmute (sound|volume)|zapni zvuk|obnov zvuk)$", re.I), "unmute_volume", {}),
        (re.compile(r"^(volume up|increase volume|zvýš hlasitosť|zvys hlasitost|hlasnejšie|hlasnejsie)$", re.I), "volume_up", {}),
        (re.compile(r"^(volume down|decrease volume|zníž hlasitosť|zniz hlasitost|tichšie|tichsie)$", re.I), "volume_down", {}),
        (re.compile(r"^(show desktop|ukáž plochu|ukaz plochu|zobraz plochu)$", re.I), "show_desktop", {}),
        (re.compile(r"^(what is playing|current track|čo hrá|čo práve hrá|co hra|co prave hra)$", re.I), "get_current_track", {}),
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
    _argument_routes: tuple[tuple[re.Pattern[str], str], ...] = (
        (re.compile(r"^(?:(?:či|ci) by (?:si )?mi (?:ne)?vedel\s+)?(?:vyhľadaj|vyhladaj|vyhľadať|vyhladat|nájdi|najdi)\s+(?P<site>.+?)\s+a\s+(?:choď|chod|ísť|ist|prejdi|otvor)\s+(?:na|do)\s+(?:časť|cast|sekciu)(?:\s+stránky|\s+stranky)?(?:\s+kde\s+(?:sú|su))?\s+(?P<section>.+?)[?.!]*$", re.I), "open_web_section"),
        (re.compile(r"^(?:find|search for)\s+(?P<site>.+?)\s+and\s+(?:open|go to)\s+(?:the\s+)?(?P<section>.+?)(?:\s+section)?[?.!]*$", re.I), "open_web_section"),
        (re.compile(r"^(?:play|pusti|prehraj)\s+(?:on\s+youtube|na\s+youtube|youtube)\s+(?P<query>.+)$", re.I), "play_youtube"),
        (re.compile(r"^(?:play|pusti|prehraj)\s+(?P<query>.+?)\s+(?:on|na)\s+youtube$", re.I), "play_youtube"),
        (re.compile(r"^(?:search|find|vyhľadaj|vyhladaj|nájdi|najdi)\s+(?:on\s+youtube|na\s+youtube|youtube)\s+(?P<query>.+?)(?:\s+a\s+(?:play|pusti|prehraj)(?:\s+(?:it|to))?)?$", re.I), "play_youtube"),
        (re.compile(r"^(?:search (?:the )?web for|google|vyhľadaj na webe|vyhladaj na webe|vygoogli)\s+(?P<query>.+)$", re.I), "search_public_web"),
        (re.compile(r"^(?:search(?: for)?|vyhľadaj|vyhladaj|nájdi|najdi)\s+(?P<query>(?!(?:súbor|subor|file|priečinok|priecinok|folder)\b).+)$", re.I), "search_web_in_browser"),
    )
    _cancel = {"cancel", "stop", "stop speaking", "prestaň", "ticho", "zruš"}

    def route(self, text: str, available_tools: set[str]) -> ToolCall | str | None:
        normalized = " ".join(text.strip().split())
        if normalized.casefold() in self._cancel:
            return "Cancelled."
        for pattern, tool_name in self._argument_routes:
            match = pattern.fullmatch(normalized)
            if match and tool_name in available_tools:
                arguments = {
                    key: value.strip() for key, value in match.groupdict().items() if value is not None
                }
                return ToolCall(
                    function=FunctionCall(name=tool_name, arguments=arguments)
                )
        for pattern, tool_name, arguments in self._routes:
            if tool_name in available_tools and pattern.search(normalized):
                return ToolCall(function=FunctionCall(name=tool_name, arguments=dict(arguments)))
        return None
