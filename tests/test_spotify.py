import asyncio

import httpx
import pytest

from config import SpotifyConfig
from tools.spotify import SpotifyClient, SpotifyError


def test_spotify_is_disabled_and_tokenless_by_default(monkeypatch) -> None:
    monkeypatch.delenv("SPOTIFY_ACCESS_TOKEN", raising=False)
    client = SpotifyClient(SpotifyConfig())
    assert not client.available
    with pytest.raises(SpotifyError, match="disabled"):
        client._token()


def test_spotify_uses_official_endpoint_and_environment_token(monkeypatch) -> None:
    monkeypatch.setenv("SPOTIFY_ACCESS_TOKEN", "local-test-token")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api.spotify.com/v1/me/player/next"
        assert request.method == "POST"
        assert request.headers["Authorization"] == "Bearer local-test-token"
        return httpx.Response(204)

    client = SpotifyClient(SpotifyConfig(enabled=True), httpx.MockTransport(handler))
    result = asyncio.run(client.command("next"))
    assert result == {"backend": "spotify_web_api", "action": "next", "confirmed": True}
