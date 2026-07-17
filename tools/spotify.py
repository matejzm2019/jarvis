"""Optional official Spotify Web API client; disabled by default."""

from __future__ import annotations

import os
from typing import Any

import httpx

from config import SpotifyConfig


class SpotifyError(RuntimeError):
    """A configured Spotify Web API request failed safely."""


class SpotifyClient:
    """Use an explicit environment token without persisting or logging it."""

    API = "https://api.spotify.com/v1/me/player"

    def __init__(self, config: SpotifyConfig, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.config = config
        self.transport = transport

    @property
    def available(self) -> bool:
        return self.config.enabled and bool(os.environ.get(self.config.access_token_environment_variable))

    def _token(self) -> str:
        token = os.environ.get(self.config.access_token_environment_variable, "").strip()
        if not self.config.enabled:
            raise SpotifyError("Spotify API integration is disabled")
        if not token:
            raise SpotifyError(
                f"Spotify token is missing from environment variable {self.config.access_token_environment_variable}"
            )
        return token

    async def _request(self, method: str, suffix: str = "", **kwargs: Any) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self._token()}"}
        async with httpx.AsyncClient(
            timeout=self.config.request_timeout_seconds, transport=self.transport
        ) as client:
            response = await client.request(method, self.API + suffix, headers=headers, **kwargs)
        if response.status_code not in {200, 204}:
            raise SpotifyError(f"Spotify Web API returned HTTP {response.status_code}")
        return response

    async def command(self, action: str) -> dict[str, Any]:
        methods = {
            "play": ("PUT", "/play"), "pause": ("PUT", "/pause"),
            "stop": ("PUT", "/pause"), "next": ("POST", "/next"),
            "previous": ("POST", "/previous"),
        }
        try:
            method, suffix = methods[action]
        except KeyError as exc:
            raise SpotifyError(f"Unsupported Spotify action: {action}") from exc
        await self._request(method, suffix)
        return {"backend": "spotify_web_api", "action": action, "confirmed": True}

    async def current_track(self) -> dict[str, Any]:
        response = await self._request("GET")
        payload = response.json()
        item = payload.get("item") or {}
        artists = item.get("artists") or []
        return {
            "backend": "spotify_web_api",
            "title": item.get("name") or "",
            "artist": ", ".join(str(entry.get("name", "")) for entry in artists if isinstance(entry, dict)),
            "album": (item.get("album") or {}).get("name", ""),
            "status": "playing" if payload.get("is_playing") else "paused",
            "volume_percent": (payload.get("device") or {}).get("volume_percent"),
        }

    async def set_volume(self, percent: int) -> dict[str, Any]:
        await self._request("PUT", "/volume", params={"volume_percent": percent})
        return {"backend": "spotify_web_api", "volume_percent": percent, "confirmed": True}
