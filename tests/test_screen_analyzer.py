import asyncio
import json

from PIL import Image

from assistant.models import ChatMessage, ChatResponse
from config import VisionConfig
from vision.screen_analyzer import ScreenAnalyzer
from vision.screenshot import ScreenCapture


class FakeClient:
    def __init__(self, content: str) -> None:
        self.content = content
        self.messages: list[ChatMessage] = []
        self.format_schema = None

    async def chat(self, messages, *, stream=False, format_schema=None):
        self.messages = messages
        self.format_schema = format_schema
        message = ChatMessage(role="assistant", content=self.content)
        return ChatResponse(content=self.content, message=message)


class FakeScreenshots:
    def capture_screen(self) -> ScreenCapture:
        return ScreenCapture(
            Image.new("RGB", (200, 100), "blue"),
            "screen",
            10,
            20,
            {"left": 10, "top": 20, "width": 200, "height": 100},
        )


def test_analyzer_sends_image_only_to_local_client() -> None:
    async def run() -> None:
        client = FakeClient("A blue test screen.")
        analyzer = ScreenAnalyzer(VisionConfig(), client, screenshots=FakeScreenshots())
        result = await analyzer.analyze("Describe it", "screen")
        assert result.text == "A blue test screen."
        assert client.messages[1].images and len(client.messages[1].images[0]) > 20
        assert "untrusted" in client.messages[0].content

    asyncio.run(run())


def test_located_coordinates_are_validated_and_mapped() -> None:
    async def run() -> None:
        payload = json.dumps(
            {"found": True, "label": "button", "description": "Found it", "confidence": 0.9,
             "left": 250, "top": 250, "right": 450, "bottom": 450}
        )
        client = FakeClient(payload)
        analyzer = ScreenAnalyzer(VisionConfig(), client, screenshots=FakeScreenshots())
        result = await analyzer.locate("button", "screen")
        assert result.metadata["coordinates"] == {
            "x": 60, "y": 45, "width": 40, "height": 20,
            "center_x": 80, "center_y": 55, "coordinate_space": "virtual_desktop_pixels",
        }
        assert result.metadata["coordinates_validated"] is True
        assert client.format_schema["title"] == "LocatedElement"

    asyncio.run(run())


def test_located_coordinates_cannot_overflow_capture_edge() -> None:
    async def run() -> None:
        payload = json.dumps(
            {"found": True, "label": "edge", "description": "", "confidence": 0.5,
             "left": 999, "top": 999, "right": 1000, "bottom": 1000}
        )
        analyzer = ScreenAnalyzer(VisionConfig(), FakeClient(payload), screenshots=FakeScreenshots())
        result = await analyzer.locate("edge", "screen")
        coordinates = result.metadata["coordinates"]
        assert coordinates["x"] + coordinates["width"] <= 210
        assert coordinates["y"] + coordinates["height"] <= 120

    asyncio.run(run())
