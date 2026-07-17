"""Startup validation helpers."""

from __future__ import annotations

import os
import platform
from pathlib import Path

from config import JarvisConfig


def validate_runtime(config: JarvisConfig) -> list[str]:
    """Return non-fatal local setup warnings."""
    warnings: list[str] = []
    if platform.system() != "Windows":
        warnings.append("Jarvis desktop actions require Windows 11.")
    missing = [str(path) for path in config.searchable_paths() if not path.is_dir()]
    if missing:
        warnings.append(f"Searchable directories not found: {', '.join(missing)}")
    missing_music = [str(path) for path in config.music_paths() if not path.is_dir()]
    if missing_music:
        warnings.append(f"Music directories not found: {', '.join(missing_music)}")
    if not config.text_to_speech.executable_path:
        warnings.append("Piper executable is not configured; voice output is unavailable.")
    elif not Path(config.text_to_speech.executable_path).is_file():
        warnings.append("Configured Piper executable does not exist.")
    if not config.text_to_speech.voice_model_path:
        warnings.append("Primary Piper voice model is not configured; voice output is unavailable.")
    elif not Path(config.text_to_speech.voice_model_path).is_file():
        warnings.append("Configured Piper voice model does not exist.")
    browser_names = {
        label.casefold()
        for app in config.applications.allowlist
        for label in (app.name, *app.aliases)
    }
    if config.browser.preferred_browser.casefold() not in browser_names:
        warnings.append("Preferred browser is not present in the application allowlist.")
    if config.spotify.enabled and not os.environ.get(config.spotify.access_token_environment_variable):
        warnings.append(
            f"Spotify is enabled but {config.spotify.access_token_environment_variable} is not set; Windows media controls will be used."
        )
    return warnings
