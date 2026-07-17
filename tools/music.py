"""Bounded local music discovery and playback."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz

from assistant.models import RiskLevel, ToolResult
from config import JarvisConfig
from tools.base import BaseTool
from tools.files import PathArguments, PathPolicy, SearchArguments

AUDIO_SUFFIXES = {".mp3", ".flac", ".wav", ".m4a", ".aac", ".ogg", ".opus", ".wma"}


class MusicLibrary:
    """Search only configured music roots and accepted audio extensions."""

    def __init__(self, config: JarvisConfig) -> None:
        self.policy = PathPolicy(config.music_paths())
        self.max_results = config.music.max_search_results

    def search(self, query: str, max_results: int) -> list[dict[str, Any]]:
        matches: list[tuple[int, Path]] = []
        folded = query.casefold()
        for current, _, files in self.policy.walk():
            for name in files:
                path = current / name
                if path.suffix.casefold() not in AUDIO_SUFFIXES or not self.policy.is_allowed(path):
                    continue
                score = 100 if folded in path.stem.casefold() else fuzz.WRatio(folded, path.stem.casefold())
                if score >= 55:
                    matches.append((score, path))
        matches.sort(key=lambda item: (-item[0], item[1].name.casefold()))
        return [
            {"name": path.name, "path": str(path), "size_bytes": path.stat().st_size, "match_score": score}
            for score, path in matches[: min(max_results, self.max_results)]
        ]

    def play(self, raw_path: str) -> Path:
        path = self.policy.require(raw_path, kind="file")
        if path.suffix.casefold() not in AUDIO_SUFFIXES:
            raise ValueError("The selected file is not a supported local audio format")
        if os.name != "nt" or not hasattr(os, "startfile"):
            raise RuntimeError("Local audio playback is supported only on Windows")
        os.startfile(str(path))  # type: ignore[attr-defined]
        return path


class SearchLocalMusicTool(BaseTool[SearchArguments]):
    name = "search_local_music"
    description = "Search supported audio filenames only inside configured local music directories."
    argument_model = SearchArguments
    timeout_seconds = 30

    def __init__(self, library: MusicLibrary) -> None:
        super().__init__()
        self.library = library

    async def execute(self, arguments: SearchArguments) -> ToolResult:
        tracks = await asyncio.to_thread(self.library.search, arguments.query, arguments.max_results)
        return ToolResult(success=True, tool=self.name, message=f"Found {len(tracks)} local tracks.", data={"tracks": tracks})


class PlayLocalAudioFileTool(BaseTool[PathArguments]):
    name = "play_local_audio_file"
    description = "Open one validated audio file from configured music directories in its Windows player."
    argument_model = PathArguments
    risk = RiskLevel.MEDIUM

    def __init__(self, library: MusicLibrary) -> None:
        super().__init__()
        self.library = library

    async def execute(self, arguments: PathArguments) -> ToolResult:
        path = await asyncio.to_thread(self.library.play, arguments.path)
        return ToolResult(success=True, tool=self.name, message=f"Started {path.name}.", data={"path": str(path)})


def build_music_tools(config: JarvisConfig) -> list[BaseTool]:
    """Build local music tools sharing one validated library."""
    library = MusicLibrary(config)
    return [SearchLocalMusicTool(library), PlayLocalAudioFileTool(library)]
