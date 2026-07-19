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


def test_routes_general_time_and_video_controls_without_llm() -> None:
    tools = {"get_current_time", "pause_music", "mute_volume", "unmute_volume"}
    router = IntentRouter()
    assert router.route("Koľko je teraz hodín?", tools).function.name == "get_current_time"
    assert router.route("Aky je teraz cas?", tools).function.name == "get_current_time"
    assert router.route("pozastav video", tools).function.name == "pause_music"
    assert router.route("stlm zvuk", tools).function.name == "mute_volume"
    assert router.route("zapni zvuk", tools).function.name == "unmute_volume"


def test_routes_youtube_and_public_web_queries() -> None:
    tools = {"play_youtube", "search_public_web"}
    router = IntentRouter()
    youtube = router.route("Pusti na YouTube Daft Punk Around the World", tools)
    assert youtube.function.name == "play_youtube"
    assert youtube.function.arguments["query"] == "Daft Punk Around the World"
    web = router.route("Vyhľadaj na webe počasie Bratislava", tools)
    assert web.function.name == "search_public_web"
    assert web.function.arguments["query"] == "počasie Bratislava"


def test_routes_site_section_and_basic_search_without_llm() -> None:
    tools = {"open_web_section", "search_web_in_browser"}
    router = IntentRouter()
    section = router.route(
        "Ci by mi nevedel vyhladat My Forza a ist na cast stranky kde su screenshoty", tools
    )
    assert section.function.name == "open_web_section"
    assert section.function.arguments == {"site": "My Forza", "section": "screenshoty"}
    search = router.route("Vyhladaj herný volant", tools)
    assert search.function.name == "search_web_in_browser"
    assert search.function.arguments["query"] == "herný volant"
