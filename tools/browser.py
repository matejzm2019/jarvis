"""Safe browser launch and explicit public web-search tools."""

from __future__ import annotations

import asyncio
import os
from urllib.parse import quote_plus

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from assistant.models import RiskLevel, ToolResult
from config import BrowserConfig
from tools.applications import ApplicationCatalog
from tools.base import BaseTool, EmptyArguments


class WebsiteArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: HttpUrl

    @field_validator("url")
    @classmethod
    def no_embedded_credentials(cls, value: HttpUrl) -> HttpUrl:
        if value.username or value.password:
            raise ValueError("URLs containing credentials are forbidden")
        return value


class WebSearchArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    query: str = Field(min_length=1, max_length=500)


class BrowserArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    browser: str | None = Field(default=None, min_length=1, max_length=120)


class BrowserService:
    """Open public URLs without reading browser state, profiles, cookies, or content."""

    def __init__(self, catalog: ApplicationCatalog, config: BrowserConfig) -> None:
        self.catalog = catalog
        self.config = config

    @staticmethod
    def open_url(url: str) -> None:
        if os.name != "nt" or not hasattr(os, "startfile"):
            raise RuntimeError("Browser launch is supported only on Windows")
        os.startfile(url)  # type: ignore[attr-defined]

    def open_browser(self, browser: str | None) -> dict[str, str]:
        target = self.catalog.resolve(browser or self.config.preferred_browser)
        if target.path is None:
            raise FileNotFoundError("No trusted browser launch path was found")
        os.startfile(str(target.path))  # type: ignore[attr-defined]
        return {"application": target.name, "source": target.source}

    def focus_browser(self, browser: str | None) -> dict[str, object]:
        return self.catalog.focus(browser or self.config.preferred_browser)


class OpenWebsiteTool(BaseTool[WebsiteArguments]):
    name = "open_website"
    description = "Open an explicit HTTP/HTTPS URL in the default browser without reading browser content."
    argument_model = WebsiteArguments
    risk = RiskLevel.MEDIUM

    async def execute(self, arguments: WebsiteArguments) -> ToolResult:
        url = str(arguments.url)
        await asyncio.to_thread(BrowserService.open_url, url)
        return ToolResult(success=True, tool=self.name, message=f"Opened {arguments.url.host}.", data={"url": url})


class SearchWebInBrowserTool(BaseTool[WebSearchArguments]):
    name = "search_web_in_browser"
    description = "Open an explicit user-requested public web search; the query is sent to the configured search site."
    argument_model = WebSearchArguments
    risk = RiskLevel.MEDIUM

    def __init__(self, service: BrowserService) -> None:
        super().__init__()
        self.service = service

    async def execute(self, arguments: WebSearchArguments) -> ToolResult:
        url = self.service.config.search_url.format(query=quote_plus(arguments.query))
        await asyncio.to_thread(self.service.open_url, url)
        return ToolResult(success=True, tool=self.name, message="Opened the web search in your browser.")


class OpenBrowserTool(BaseTool[BrowserArguments]):
    name = "open_browser"
    description = "Open an allowlisted browser using trusted configured or Windows application sources."
    argument_model = BrowserArguments
    risk = RiskLevel.MEDIUM

    def __init__(self, service: BrowserService) -> None:
        super().__init__()
        self.service = service

    async def execute(self, arguments: BrowserArguments) -> ToolResult:
        data = await asyncio.to_thread(self.service.open_browser, arguments.browser)
        return ToolResult(success=True, tool=self.name, message=f"Opened {data['application']}.", data=data)


class FocusBrowserTool(OpenBrowserTool):
    name = "focus_browser"
    description = "Focus a visible window of an allowlisted browser."

    async def execute(self, arguments: BrowserArguments) -> ToolResult:
        data = await asyncio.to_thread(self.service.focus_browser, arguments.browser)
        return ToolResult(success=True, tool=self.name, message=f"Focused {data['name']}.", data=data)


def build_browser_tools(catalog: ApplicationCatalog, config: BrowserConfig) -> list[BaseTool]:
    """Build browser tools sharing the allowlisted application catalog."""
    service = BrowserService(catalog, config)
    return [OpenWebsiteTool(), SearchWebInBrowserTool(service), OpenBrowserTool(service), FocusBrowserTool(service)]
