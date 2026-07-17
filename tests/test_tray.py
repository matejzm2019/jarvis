from assistant.state import AssistantStatus
from ui.tray import create_status_icon


def test_tray_icons_are_generated_locally() -> None:
    sleeping = create_status_icon(AssistantStatus.SLEEPING, 32)
    error = create_status_icon(AssistantStatus.ERROR, 32)
    assert sleeping.size == (32, 32)
    assert sleeping.tobytes() != error.tobytes()
