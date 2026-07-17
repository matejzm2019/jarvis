"""Windows media-session and system-volume tools."""

from __future__ import annotations

import asyncio
import unicodedata
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from assistant.models import RiskLevel, ToolResult
from config import JarvisConfig
from tools.base import BaseTool, EmptyArguments
from tools.spotify import SpotifyClient

try:
    import win32api
    import win32con
except ImportError:  # pragma: no cover
    win32api = win32con = None  # type: ignore[assignment]

try:
    from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager
except ImportError:  # pragma: no cover
    GlobalSystemMediaTransportControlsSessionManager = None  # type: ignore[assignment]

_MEDIA_KEYS = {"play": 0xB3, "pause": 0xB3, "next": 0xB0, "previous": 0xB1, "stop": 0xB2}
_PLAYBACK_STATUS = {0: "closed", 1: "opened", 2: "changing", 3: "stopped", 4: "playing", 5: "paused"}


class VolumeArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    percent: int = Field(ge=0, le=100)


class WindowsMediaController:
    """Control the active GSMTC session with a predefined media-key fallback."""

    def __init__(self, spotify: SpotifyClient | None = None) -> None:
        self.spotify = spotify

    async def _session(self) -> Any | None:
        if GlobalSystemMediaTransportControlsSessionManager is None:
            return None
        manager = await GlobalSystemMediaTransportControlsSessionManager.request_async()
        return manager.get_current_session()

    @staticmethod
    def _press_media_key(action: str) -> None:
        if win32api is None or win32con is None:
            raise RuntimeError("pywin32 is required for the media-key fallback")
        key = _MEDIA_KEYS[action]
        win32api.keybd_event(key, 0, 0, 0)
        win32api.keybd_event(key, 0, win32con.KEYEVENTF_KEYUP, 0)

    async def command(self, action: str) -> dict[str, Any]:
        if self.spotify and self.spotify.available:
            return await self.spotify.command(action)
        session = await self._session()
        method_names = {
            "play": "try_play_async", "pause": "try_pause_async", "stop": "try_stop_async",
            "next": "try_skip_next_async", "previous": "try_skip_previous_async",
        }
        if session is not None:
            confirmed = bool(await getattr(session, method_names[action])())
            return {
                "backend": "windows_media_session", "action": action,
                "confirmed": confirmed, "application": session.source_app_user_model_id,
            }
        await asyncio.to_thread(self._press_media_key, action)
        return {"backend": "windows_media_key", "action": action, "confirmed": False}

    async def current_track(self) -> dict[str, Any]:
        if self.spotify and self.spotify.available:
            return await self.spotify.current_track()
        session = await self._session()
        if session is None:
            raise RuntimeError("No active Windows media session is available")
        properties = await session.try_get_media_properties_async()
        playback = session.get_playback_info()
        status = _PLAYBACK_STATUS.get(int(playback.playback_status), "unknown")
        return {
            "backend": "windows_media_session",
            "application": session.source_app_user_model_id,
            "title": unicodedata.normalize("NFKC", properties.title),
            "artist": unicodedata.normalize("NFKC", properties.artist),
            "album": unicodedata.normalize("NFKC", properties.album_title),
            "status": status,
        }

    async def set_volume(self, percent: int) -> dict[str, Any]:
        if self.spotify and self.spotify.available:
            return await self.spotify.set_volume(percent)

        def set_local() -> None:
            from pycaw.pycaw import AudioUtilities

            AudioUtilities.GetSpeakers().EndpointVolume.SetMasterVolumeLevelScalar(percent / 100, None)

        await asyncio.to_thread(set_local)
        return {"backend": "windows_core_audio", "volume_percent": percent, "confirmed": True}


class _MediaActionTool(BaseTool[EmptyArguments]):
    argument_model = EmptyArguments
    action: str

    def __init__(self, controller: WindowsMediaController) -> None:
        super().__init__()
        self.controller = controller

    async def execute(self, arguments: EmptyArguments) -> ToolResult:
        data = await self.controller.command(self.action)
        message = f"Media action {self.action} was sent."
        if not data["confirmed"]:
            message += " Windows did not expose playback confirmation."
        return ToolResult(success=True, tool=self.name, message=message, data=data)


class PlayMusicTool(_MediaActionTool):
    name = "play_music"
    description = "Resume playback in the configured Spotify API or active local Windows media session."
    action = "play"


class PauseMusicTool(_MediaActionTool):
    name = "pause_music"
    description = "Pause the configured Spotify API or active local Windows media session."
    action = "pause"


class ResumeMusicTool(PlayMusicTool):
    name = "resume_music"
    description = "Resume the current media session."


class StopMusicTool(_MediaActionTool):
    name = "stop_music"
    description = "Stop the current media session; Spotify maps this safely to pause."
    action = "stop"


class NextTrackTool(_MediaActionTool):
    name = "next_track"
    description = "Skip to the next track in the active media session."
    action = "next"


class PreviousTrackTool(_MediaActionTool):
    name = "previous_track"
    description = "Skip to the previous track in the active media session."
    action = "previous"


class GetCurrentTrackTool(BaseTool[EmptyArguments]):
    name = "get_current_track"
    description = "Read current track metadata from Spotify API or the active Windows media session."
    argument_model = EmptyArguments

    def __init__(self, controller: WindowsMediaController) -> None:
        super().__init__()
        self.controller = controller

    async def execute(self, arguments: EmptyArguments) -> ToolResult:
        data = await self.controller.current_track()
        title = data.get("title") or "unknown track"
        artist = data.get("artist") or "unknown artist"
        return ToolResult(success=True, tool=self.name, message=f"Current track: {title} by {artist}.", data=data)


class SetMediaVolumeTool(BaseTool[VolumeArguments]):
    name = "set_media_volume"
    description = "Set Spotify playback volume when configured, otherwise Windows system output volume."
    argument_model = VolumeArguments
    risk = RiskLevel.MEDIUM

    def __init__(self, controller: WindowsMediaController) -> None:
        super().__init__()
        self.controller = controller

    async def execute(self, arguments: VolumeArguments) -> ToolResult:
        data = await self.controller.set_volume(arguments.percent)
        return ToolResult(success=True, tool=self.name, message=f"Set volume to {arguments.percent}%.", data=data)


def build_media_tools(config: JarvisConfig) -> list[BaseTool]:
    """Build one shared media controller and all typed media tools."""
    controller = WindowsMediaController(SpotifyClient(config.spotify))
    return [
        PlayMusicTool(controller), PauseMusicTool(controller), ResumeMusicTool(controller),
        StopMusicTool(controller), NextTrackTool(controller), PreviousTrackTool(controller),
        GetCurrentTrackTool(controller), SetMediaVolumeTool(controller),
    ]
