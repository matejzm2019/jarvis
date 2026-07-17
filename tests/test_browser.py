import asyncio

import pytest
from pydantic import ValidationError

from config import BrowserConfig
from tools.browser import SearchWebInBrowserTool, WebSearchArguments, WebsiteArguments


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
