from assistant.intent_router import IntentRouter


VISION_TOOLS = {"describe_screen", "summarize_visible_content", "read_visible_error_message"}


def test_routes_simple_slovak_screen_request() -> None:
    call = IntentRouter().route("Čo vidíš na obrazovke?", VISION_TOOLS)
    assert call.function.name == "describe_screen"
    assert "slovensky" in call.function.arguments["focus"]


def test_routes_this_window_to_active_window() -> None:
    call = IntentRouter().route("Summarize this window.", VISION_TOOLS)
    assert call.function.name == "summarize_visible_content"
    assert call.function.arguments["scope"] == "active_window"
