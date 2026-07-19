"""Validated local tkinter settings editor for Jarvis."""

from __future__ import annotations

import copy
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from config import JarvisConfig
from ui.tk_host import TkHost

TEXT_FIELDS = (
    ("ollama_base_url", "Ollama base URL"),
    ("ollama_model", "Ollama model"),
    ("ollama_context", "Context size"),
    ("microphone", "Microphone device/index"),
    ("whisper_model", "Whisper model"),
    ("speech_language", "Speech language (auto/sk/en)"),
    ("piper_executable", "Piper executable"),
    ("piper_voice", "Piper Slovak/default voice"),
    ("piper_english_voice", "Piper English voice"),
    ("piper_rate", "Piper speaking rate"),
    ("max_spoken_characters", "Maximum spoken characters"),
    ("max_spoken_sentences", "Maximum spoken sentences"),
    ("wake_phrase", "Wake phrase"),
    ("wake_sensitivity", "Wake sensitivity"),
    ("wake_resume_delay", "Wake resume delay after speech (seconds)"),
    ("push_to_talk", "Push-to-talk hotkey"),
    ("stop_speaking", "Stop-speaking hotkey"),
    ("ui_language", "UI language (auto/sk/en)"),
    ("vision_width", "Screenshot max width"),
    ("vision_height", "Screenshot max height"),
    ("logging_level", "Logging level"),
    ("preferred_browser", "Preferred browser allowlist name"),
    ("browser_search_url", "Browser search HTTPS template"),
    ("web_timeout", "Public web timeout (seconds)"),
    ("web_page_characters", "Maximum public page characters"),
    ("web_search_results", "Maximum public search results"),
    ("spotify_token_env", "Spotify access-token environment variable"),
)
MULTILINE_FIELDS = (
    ("searchable_directories", "Searchable directories (one per line)"),
    ("music_directories", "Local music directories (one per line)"),
    ("allowed_applications", "Allowed apps: name | executable | aliases"),
)
BOOLEAN_FIELDS = (
    ("wake_enabled", "Enable wake word"),
    ("medium_notifications", "Notify for medium-risk actions"),
    ("high_confirmation", "Confirm high-risk actions"),
    ("debug", "Debug logging"),
    ("save_debug_screenshots", "Keep debug screenshots"),
    ("background", "Background mode"),
    ("spotify_enabled", "Enable optional Spotify Web API"),
    ("web_access_enabled", "Enable public web reading/search"),
    ("discover_applications", "Discover installed apps and Steam games"),
)


def _device_value(value: str) -> str | int | None:
    stripped = value.strip()
    if not stripped:
        return None
    return int(stripped) if stripped.isdecimal() else stripped


def settings_values(data: dict[str, Any]) -> dict[str, Any]:
    """Flatten supported YAML settings for the local form."""
    apps = data.get("applications", {}).get("allowlist", [])
    app_lines = []
    for app in apps:
        aliases = ", ".join(app.get("aliases", []))
        app_lines.append(f"{app.get('name', '')} | {app.get('executable_path', '')} | {aliases}")
    return {
        "ollama_base_url": str(data.get("ollama", {}).get("base_url", "")),
        "ollama_model": str(data.get("ollama", {}).get("model", "")),
        "ollama_context": str(data.get("ollama", {}).get("context_size", 65536)),
        "microphone": str(data.get("audio", {}).get("microphone_device") or ""),
        "whisper_model": str(data.get("speech_to_text", {}).get("model", "medium")),
        "speech_language": str(data.get("speech_to_text", {}).get("language", "auto")),
        "piper_executable": str(data.get("text_to_speech", {}).get("executable_path", "")),
        "piper_voice": str(data.get("text_to_speech", {}).get("voice_model_path", "")),
        "piper_english_voice": str(data.get("text_to_speech", {}).get("english_voice_model_path", "")),
        "piper_rate": str(data.get("text_to_speech", {}).get("speaking_rate", 0.9)),
        "max_spoken_characters": str(data.get("text_to_speech", {}).get("max_spoken_characters", 420)),
        "max_spoken_sentences": str(data.get("text_to_speech", {}).get("max_spoken_sentences", 3)),
        "wake_phrase": str(data.get("wake_word", {}).get("phrase", "Jarvis")),
        "wake_sensitivity": str(data.get("wake_word", {}).get("sensitivity", 0.5)),
        "wake_resume_delay": str(data.get("wake_word", {}).get("resume_delay_seconds", 1.0)),
        "push_to_talk": str(data.get("hotkeys", {}).get("push_to_talk", "ctrl+alt+space")),
        "stop_speaking": str(data.get("hotkeys", {}).get("stop_speaking", "ctrl+alt+x")),
        "ui_language": str(data.get("ui", {}).get("language", "auto")),
        "vision_width": str(data.get("vision", {}).get("max_width", 1600)),
        "vision_height": str(data.get("vision", {}).get("max_height", 900)),
        "logging_level": str(data.get("logging", {}).get("level", "INFO")),
        "preferred_browser": str(data.get("browser", {}).get("preferred_browser", "Chrome")),
        "browser_search_url": str(data.get("browser", {}).get("search_url", "https://www.google.com/search?q={query}")),
        "web_timeout": str(data.get("browser", {}).get("request_timeout_seconds", 15)),
        "web_page_characters": str(data.get("browser", {}).get("max_page_characters", 12000)),
        "web_search_results": str(data.get("browser", {}).get("max_search_results", 5)),
        "spotify_token_env": str(data.get("spotify", {}).get("access_token_environment_variable", "SPOTIFY_ACCESS_TOKEN")),
        "searchable_directories": "\n".join(data.get("files", {}).get("searchable_directories", [])),
        "music_directories": "\n".join(data.get("music", {}).get("directories", ["Music"])),
        "allowed_applications": "\n".join(app_lines),
        "wake_enabled": bool(data.get("wake_word", {}).get("enabled", True)),
        "medium_notifications": bool(data.get("permissions", {}).get("medium_action_notifications", True)),
        "high_confirmation": bool(data.get("permissions", {}).get("high_action_confirmation", True)),
        "debug": bool(data.get("logging", {}).get("debug", False)),
        "save_debug_screenshots": bool(data.get("vision", {}).get("save_debug_screenshots", False)),
        "background": bool(data.get("ui", {}).get("background", False)),
        "spotify_enabled": bool(data.get("spotify", {}).get("enabled", False)),
        "web_access_enabled": bool(data.get("browser", {}).get("web_access_enabled", True)),
        "discover_applications": bool(data.get("applications", {}).get("allow_discovered_applications", True)),
    }


def apply_settings_values(data: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    """Apply form values to YAML data and validate the complete configuration."""
    updated = copy.deepcopy(data)
    for section in (
        "ollama", "audio", "speech_to_text", "text_to_speech", "wake_word", "hotkeys",
        "ui", "vision", "logging", "files", "applications", "permissions",
        "music", "spotify", "browser",
    ):
        updated.setdefault(section, {})
    updated["ollama"].update(
        base_url=str(values["ollama_base_url"]).strip(),
        model=str(values["ollama_model"]).strip(),
        context_size=int(values["ollama_context"]),
    )
    updated["audio"]["microphone_device"] = _device_value(str(values["microphone"]))
    updated["speech_to_text"].update(
        model=str(values["whisper_model"]).strip(), language=str(values["speech_language"]).strip()
    )
    updated["text_to_speech"].update(
        executable_path=str(values["piper_executable"]).strip(),
        voice_model_path=str(values["piper_voice"]).strip(),
        english_voice_model_path=str(values["piper_english_voice"]).strip(),
        speaking_rate=float(values["piper_rate"]),
        max_spoken_characters=int(values["max_spoken_characters"]),
        max_spoken_sentences=int(values["max_spoken_sentences"]),
    )
    updated["wake_word"].update(
        enabled=bool(values["wake_enabled"]),
        phrase=str(values["wake_phrase"]).strip(),
        sensitivity=float(values["wake_sensitivity"]),
        resume_delay_seconds=float(values["wake_resume_delay"]),
    )
    updated["hotkeys"].update(
        push_to_talk=str(values["push_to_talk"]).strip(),
        stop_speaking=str(values["stop_speaking"]).strip(),
    )
    updated["ui"].update(language=str(values["ui_language"]).strip(), background=bool(values["background"]))
    updated["vision"].update(
        max_width=int(values["vision_width"]),
        max_height=int(values["vision_height"]),
        save_debug_screenshots=bool(values["save_debug_screenshots"]),
    )
    updated["logging"].update(level=str(values["logging_level"]).strip().upper(), debug=bool(values["debug"]))
    updated["browser"].update(
        preferred_browser=str(values["preferred_browser"]).strip(),
        search_url=str(values["browser_search_url"]).strip(),
        web_access_enabled=bool(values["web_access_enabled"]),
        request_timeout_seconds=float(values["web_timeout"]),
        max_page_characters=int(values["web_page_characters"]),
        max_search_results=int(values["web_search_results"]),
    )
    updated["spotify"].update(
        enabled=bool(values["spotify_enabled"]),
        access_token_environment_variable=str(values["spotify_token_env"]).strip(),
    )
    directories = [line.strip() for line in str(values["searchable_directories"]).splitlines() if line.strip()]
    if not directories:
        raise ValueError("At least one searchable directory is required")
    updated["files"]["searchable_directories"] = directories
    music_directories = [line.strip() for line in str(values["music_directories"]).splitlines() if line.strip()]
    if not music_directories:
        raise ValueError("At least one music directory is required")
    updated["music"]["directories"] = music_directories
    apps = []
    for line in str(values["allowed_applications"]).splitlines():
        if not line.strip():
            continue
        parts = [part.strip() for part in line.split("|", 2)]
        name = parts[0]
        if not name:
            raise ValueError("Every allowed application needs a name")
        aliases = [alias.strip() for alias in parts[2].split(",") if alias.strip()] if len(parts) > 2 else []
        apps.append({"name": name, "executable_path": parts[1] if len(parts) > 1 else "", "aliases": aliases})
    updated["applications"]["allowlist"] = apps
    updated["applications"]["allow_discovered_applications"] = bool(values["discover_applications"])
    updated["permissions"].update(
        medium_action_notifications=bool(values["medium_notifications"]),
        high_action_confirmation=bool(values["high_confirmation"]),
    )
    JarvisConfig.model_validate(updated)
    return updated


class SettingsWindow:
    """Own one settings Toplevel and save atomically after Pydantic validation."""

    def __init__(
        self,
        config_path: Path,
        host: TkHost,
        on_saved: Callable[[], None] | None = None,
    ) -> None:
        self.config_path = config_path.resolve()
        self.host = host
        self.on_saved = on_saved
        self._window: Any | None = None

    def open(self) -> None:
        """Open or focus the settings editor."""
        self.host.post(self._open)

    def _open(self, root: Any) -> None:
        import tkinter as tk
        from tkinter import messagebox, ttk

        if self._window is not None and self._window.winfo_exists():
            self._window.deiconify()
            self._window.lift()
            self._window.focus_force()
            return
        raw = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        initial = settings_values(raw)
        window = tk.Toplevel(root)
        self._window = window
        window.title("Jarvis settings")
        window.geometry("760x820")
        window.minsize(650, 600)
        window.protocol("WM_DELETE_WINDOW", self._destroy)
        canvas = tk.Canvas(window, highlightthickness=0)
        scrollbar = ttk.Scrollbar(window, orient="vertical", command=canvas.yview)
        form = ttk.Frame(canvas, padding=16)
        form.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=form, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        text_vars: dict[str, tk.StringVar] = {}
        row = 0
        for key, label in TEXT_FIELDS:
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=4)
            variable = tk.StringVar(value=initial[key])
            ttk.Entry(form, textvariable=variable, width=64).grid(row=row, column=1, sticky="ew", pady=4)
            text_vars[key] = variable
            row += 1
        text_widgets: dict[str, tk.Text] = {}
        for key, label in MULTILINE_FIELDS:
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="nw", padx=(0, 12), pady=4)
            widget = tk.Text(form, width=64, height=5, wrap="none")
            widget.insert("1.0", initial[key])
            widget.grid(row=row, column=1, sticky="ew", pady=4)
            text_widgets[key] = widget
            row += 1
        bool_vars: dict[str, tk.BooleanVar] = {}
        for key, label in BOOLEAN_FIELDS:
            variable = tk.BooleanVar(value=initial[key])
            ttk.Checkbutton(form, text=label, variable=variable).grid(row=row, column=1, sticky="w", pady=3)
            bool_vars[key] = variable
            row += 1
        form.columnconfigure(1, weight=1)
        status = tk.StringVar(value="Changes require a Jarvis restart.")
        ttk.Label(form, textvariable=status).grid(row=row, column=0, columnspan=2, sticky="w", pady=(14, 6))
        row += 1

        def save() -> None:
            values: dict[str, Any] = {key: value.get() for key, value in text_vars.items()}
            values.update({key: widget.get("1.0", "end").strip() for key, widget in text_widgets.items()})
            values.update({key: value.get() for key, value in bool_vars.items()})
            try:
                current = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
                updated = apply_settings_values(current, values)
                temporary = self.config_path.with_suffix(self.config_path.suffix + ".tmp")
                temporary.write_text(yaml.safe_dump(updated, sort_keys=False, allow_unicode=True), encoding="utf-8")
                os.replace(temporary, self.config_path)
            except Exception as exc:
                messagebox.showerror("Invalid Jarvis settings", str(exc), parent=window)
                return
            status.set("Saved. Restart Jarvis to apply the settings.")
            if self.on_saved:
                self.on_saved()

        ttk.Button(form, text="Save settings", command=save).grid(row=row, column=1, sticky="e", pady=(0, 20))

    def _destroy(self) -> None:
        if self._window is not None:
            self._window.destroy()
        self._window = None

    def close(self) -> None:
        """Destroy the settings Toplevel on the shared UI thread."""
        self.host.call(lambda root: self._destroy(), timeout=3)
