import asyncio
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from config import BrowserConfig
from tools.browser import PublicWebService, SearchWebInBrowserTool, WebSearchArguments, WebsiteArguments


class FakeBrowserService:
    def __init__(self) -> None:
        self.config = BrowserConfig(search_url="https://search.example/?q={query}")
        self.opened: list[str] = []

    def open_url(self, url: str) -> None:
        self.opened.append(url)


def test_browser_rejects_credentials_in_url() -> None:
    with pytest.raises(ValidationError, match="credentials"):
        WebsiteArguments(url="https://user:secret@example.com/")


def test_web_search_encodes_query_and_uses_configured_https_site() -> None:
    service = FakeBrowserService()
    result = asyncio.run(SearchWebInBrowserTool(service).execute(WebSearchArguments(query="jarvis slovak voice")))
    assert result.success
    assert service.opened == ["https://search.example/?q=jarvis+slovak+voice"]


def test_public_web_blocks_loopback() -> None:
    with pytest.raises(ValueError, match="loopback"):
        asyncio.run(PublicWebService(BrowserConfig())._validate_url("http://127.0.0.1/private"))


def test_public_search_parses_bounded_html_results() -> None:
    service = PublicWebService(BrowserConfig(max_search_results=1))
    service._get = AsyncMock(return_value=(
        "https://html.duckduckgo.com/html/", "text/html",
        '<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2F">Result</a>'
        '<a class="result__snippet">Public <b>snippet</b></a>',
    ))
    results = asyncio.run(service.search("query", 5))
    assert results == [{"title": "Result", "url": "https://example.com/", "snippet": "Public snippet"}]


def test_public_page_extracts_visible_text_only() -> None:
    service = PublicWebService(BrowserConfig(max_page_characters=1000))
    service._get = AsyncMock(return_value=(
        "https://example.com/", "text/html; charset=utf-8",
        "<html><title>Example</title><script>ignore()</script><body><h1>Hello</h1><p>World</p></body></html>",
    ))
    result = asyncio.run(service.read("https://example.com/"))
    assert result["title"] == "Example"
    assert "Hello World" in result["content"]
    assert "ignore" not in result["content"]


def test_youtube_result_is_converted_to_autoplay_url() -> None:
    service = PublicWebService(BrowserConfig())
    service._get = AsyncMock(return_value=(
        "https://www.youtube.com/results", "text/html",
        '{"videoRenderer":{"videoId":"abcdefghijk"}}',
    ))
    result = asyncio.run(service.youtube_video("test song"))
    assert result["video_id"] == "abcdefghijk"
    assert result["url"].endswith("v=abcdefghijk&autoplay=1")
