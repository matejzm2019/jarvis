import pytest

from audio.interruption import MOD_ALT, MOD_CONTROL, MOD_NOREPEAT, HotkeyError, parse_hotkey


def test_parses_configured_hotkeys() -> None:
    modifiers, key = parse_hotkey("ctrl+alt+space")
    assert modifiers == MOD_CONTROL | MOD_ALT | MOD_NOREPEAT
    assert key == 0x20
    assert parse_hotkey("ctrl+alt+x")[1] == ord("X")


def test_rejects_multiple_keys() -> None:
    with pytest.raises(HotkeyError, match="exactly one"):
        parse_hotkey("ctrl+x+y")

