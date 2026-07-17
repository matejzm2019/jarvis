from PIL import Image

from vision.active_window import ActiveWindowCaptureService
from vision.screenshot import ScreenCaptureService


class FakeShot:
    def __init__(self, width: int, height: int) -> None:
        self.rgb = Image.new("RGB", (width, height), "green").tobytes()


class FakeMss:
    monitors = [{"left": -100, "top": 0, "width": 300, "height": 200}]

    def __enter__(self):
        return self

    def __exit__(self, *args: object) -> None:
        pass

    def grab(self, region: dict[str, int]) -> FakeShot:
        return FakeShot(region["width"], region["height"])


def test_screen_capture_uses_virtual_desktop_bounds() -> None:
    service = ScreenCaptureService(FakeMss)
    capture = service.capture_screen()
    try:
        assert capture.image.size == (300, 200)
        assert capture.left == -100
        assert capture.metadata()["virtual_screen"]["width"] == 300
    finally:
        capture.close()


def test_active_window_capture_clamps_to_screen() -> None:
    screenshots = ScreenCaptureService(FakeMss)
    service = ActiveWindowCaptureService(
        screenshots,
        info_provider=lambda: {"handle": 7, "title": "Test", "application": "app.exe", "pid": 1},
        rect_provider=lambda _: {"left": -150, "top": 10, "width": 120, "height": 80},
    )
    capture = service.capture()
    try:
        assert capture.image.size == (70, 80)
        assert capture.window["title"] == "Test"
    finally:
        capture.close()
