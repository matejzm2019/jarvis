import pytest
from pydantic import ValidationError

from tools.keyboard_mouse import ClickArguments, HotkeyArguments, NativeInput


def test_dangerous_hotkeys_and_click_purposes_are_rejected() -> None:
    with pytest.raises(ValidationError, match="blocked"):
        HotkeyArguments(keys=["win", "r"])
    with pytest.raises(ValidationError, match="not implemented"):
        ClickArguments(x=10, y=10, purpose="click the Delete button")


def test_password_text_is_rejected_before_native_input() -> None:
    with pytest.raises(ValueError, match="forbidden"):
        NativeInput.type_text("password is hunter2")


def test_click_coordinates_must_fit_virtual_desktop(monkeypatch) -> None:
    monkeypatch.setattr(NativeInput, "_bounds", staticmethod(lambda: (0, 0, 100, 100)))
    with pytest.raises(ValueError, match="outside"):
        NativeInput.click(ClickArguments(x=100, y=10, purpose="select row"))
