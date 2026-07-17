"""Validated YAML configuration for Jarvis."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator


class StrictModel(BaseModel):
    """Base model that rejects misspelled configuration keys."""

    model_config = ConfigDict(extra="forbid", validate_default=True)


class OllamaConfig(StrictModel):
    base_url: HttpUrl = "http://localhost:11434"
    model: str = "gemma64"
    context_size: int = Field(default=65536, ge=8192, le=262144)
    temperature: float = Field(default=0.3, ge=0, le=2)
    timeout_seconds: float = Field(default=120, gt=0, le=600)
    keep_alive: str = "30m"
    retries: int = Field(default=2, ge=0, le=5)

    @field_validator("base_url")
    @classmethod
    def local_ollama_only(cls, value: HttpUrl) -> HttpUrl:
        if value.host not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("Ollama must use a loopback address; cloud endpoints are forbidden")
        return value

    @field_validator("model")
    @classmethod
    def model_required(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Ollama model cannot be empty")
        return value.strip()


class SpeechToTextConfig(StrictModel):
    provider: Literal["faster-whisper"] = "faster-whisper"
    model: str = "medium"
    language: str = "auto"
    device: str = "auto"
    compute_type: str = "auto"
    beam_size: int = Field(default=5, ge=1, le=20)
    silence_threshold: float = Field(default=0.01, ge=0, le=1)
    allow_model_download: bool = False
    cpu_threads: int = Field(default=0, ge=0, le=128)


class TextToSpeechConfig(StrictModel):
    provider: Literal["piper"] = "piper"
    executable_path: str = ""
    voice_model_path: str = ""
    english_voice_model_path: str = ""
    speaking_rate: float = Field(default=0.9, gt=0.25, le=4)
    max_spoken_characters: int = Field(default=420, ge=80, le=4000)
    max_spoken_sentences: int = Field(default=3, ge=1, le=20)
    output_device: str | int | None = None


class WakeWordConfig(StrictModel):
    enabled: bool = True
    phrase: str = "Jarvis"
    sensitivity: float = Field(default=0.5, ge=0, le=1)
    model_path: str = "assets/wake_words/hey_jarvis_v0.1.onnx"
    cooldown_seconds: float = Field(default=2.0, ge=0.5, le=30)
    resume_delay_seconds: float = Field(default=1.0, ge=0, le=10)


class HotkeyConfig(StrictModel):
    push_to_talk: str = "ctrl+alt+space"
    stop_speaking: str = "ctrl+alt+x"

    @model_validator(mode="after")
    def distinct_hotkeys(self) -> "HotkeyConfig":
        if self.push_to_talk.casefold() == self.stop_speaking.casefold():
            raise ValueError("push_to_talk and stop_speaking hotkeys must be different")
        return self


class VisionConfig(StrictModel):
    max_width: int = Field(default=1600, ge=320, le=7680)
    max_height: int = Field(default=900, ge=240, le=4320)
    jpeg_quality: int = Field(default=85, ge=30, le=100)
    save_debug_screenshots: bool = False


class PermissionConfig(StrictModel):
    medium_action_notifications: bool = True
    high_action_confirmation: bool = True


class FileConfig(StrictModel):
    searchable_directories: list[str] = Field(
        default_factory=lambda: ["Desktop", "Documents", "Downloads", "Music"], min_length=1
    )
    max_search_results: int = Field(default=30, ge=1, le=200)
    max_read_bytes: int = Field(default=100_000, ge=1024, le=2_000_000)


class MusicConfig(StrictModel):
    directories: list[str] = Field(default_factory=lambda: ["Music"], min_length=1)
    max_search_results: int = Field(default=30, ge=1, le=200)


class MemoryConfig(StrictModel):
    database_path: str = "memory/jarvis.db"
    restore_recent_messages: int = Field(default=20, ge=0, le=200)
    max_history_messages: int = Field(default=200, ge=20, le=5000)


class SpotifyConfig(StrictModel):
    enabled: bool = False
    access_token_environment_variable: str = "SPOTIFY_ACCESS_TOKEN"
    request_timeout_seconds: float = Field(default=10, gt=0, le=60)

    @field_validator("access_token_environment_variable")
    @classmethod
    def valid_environment_name(cls, value: str) -> str:
        if not value or not value.replace("_", "A").isalnum() or value[0].isdigit():
            raise ValueError("Spotify token environment variable name is invalid")
        return value


class BrowserConfig(StrictModel):
    preferred_browser: str = "Chrome"
    search_url: str = "https://www.google.com/search?q={query}"

    @field_validator("search_url")
    @classmethod
    def safe_search_template(cls, value: str) -> str:
        if not value.startswith("https://") or "{query}" not in value:
            raise ValueError("browser.search_url must be an HTTPS template containing {query}")
        return value

    @field_validator("preferred_browser")
    @classmethod
    def browser_name_required(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Preferred browser cannot be empty")
        return value.strip()


class AllowedApplication(StrictModel):
    name: str
    executable_path: str = ""
    aliases: list[str] = Field(default_factory=list)


class ApplicationConfig(StrictModel):
    allowlist: list[AllowedApplication] = Field(default_factory=list)
    fuzzy_match_threshold: int = Field(default=72, ge=50, le=100)


class AudioConfig(StrictModel):
    microphone_device: str | int | None = None
    sample_rate: int = Field(default=16000, ge=8000, le=48000)
    block_duration_ms: int = Field(default=30, ge=10, le=100)
    minimum_speech_seconds: float = Field(default=0.25, ge=0.05, le=3)
    pre_roll_seconds: float = Field(default=0.3, ge=0, le=2)
    silence_timeout_seconds: float = Field(default=1.2, ge=0.2, le=10)
    maximum_recording_seconds: float = Field(default=30, ge=1, le=300)
    store_raw_audio: bool = False


class LoggingConfig(StrictModel):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    debug: bool = False
    max_bytes: int = Field(default=2_000_000, ge=100_000)
    backup_count: int = Field(default=5, ge=1, le=20)


class UIConfig(StrictModel):
    language: Literal["auto", "sk", "en"] = "auto"
    background: bool = False


class JarvisConfig(StrictModel):
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    speech_to_text: SpeechToTextConfig = Field(default_factory=SpeechToTextConfig)
    text_to_speech: TextToSpeechConfig = Field(default_factory=TextToSpeechConfig)
    wake_word: WakeWordConfig = Field(default_factory=WakeWordConfig)
    hotkeys: HotkeyConfig = Field(default_factory=HotkeyConfig)
    vision: VisionConfig = Field(default_factory=VisionConfig)
    permissions: PermissionConfig = Field(default_factory=PermissionConfig)
    files: FileConfig = Field(default_factory=FileConfig)
    music: MusicConfig = Field(default_factory=MusicConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    spotify: SpotifyConfig = Field(default_factory=SpotifyConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    applications: ApplicationConfig = Field(default_factory=ApplicationConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    ui: UIConfig = Field(default_factory=UIConfig)

    def searchable_paths(self) -> list[Path]:
        """Resolve configured aliases without accepting arbitrary system paths."""
        profile = Path(os.environ.get("USERPROFILE", Path.home()))
        aliases = {
            "desktop": profile / "Desktop",
            "documents": profile / "Documents",
            "downloads": profile / "Downloads",
            "music": profile / "Music",
        }
        paths: list[Path] = []
        for item in self.files.searchable_directories:
            path = aliases.get(item.casefold(), Path(item).expanduser())
            paths.append(path.resolve(strict=False))
        return paths

    def music_paths(self) -> list[Path]:
        """Resolve configured music roots with the same safe profile aliases as files."""
        profile = Path(os.environ.get("USERPROFILE", Path.home()))
        aliases = {"music": profile / "Music", "downloads": profile / "Downloads"}
        return [aliases.get(item.casefold(), Path(item).expanduser()).resolve(strict=False) for item in self.music.directories]


def load_config(path: str | Path = "config.yaml") -> JarvisConfig:
    """Load and validate a Jarvis YAML file."""
    config_path = Path(path)
    if not config_path.exists():
        example = config_path.with_name("config.example.yaml")
        if not example.exists():
            raise FileNotFoundError(
                f"Configuration not found: {config_path}. Copy config.example.yaml to config.yaml."
            )
        config_path = example
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("Configuration root must be a YAML mapping")
    return JarvisConfig.model_validate(raw)
