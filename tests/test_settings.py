from config import JarvisConfig
from ui.settings_window import apply_settings_values, settings_values


def test_settings_form_updates_and_validates_config() -> None:
    data = JarvisConfig().model_dump(mode="json")
    values = settings_values(data)
    values.update(
        ollama_model="gemma64",
        microphone="3",
        wake_phrase="Jarvis",
        searchable_directories="Desktop\nMusic",
        allowed_applications="Notepad | C:\\Windows\\notepad.exe | notes",
    )
    updated = apply_settings_values(data, values)
    assert updated["audio"]["microphone_device"] == 3
    assert updated["files"]["searchable_directories"] == ["Desktop", "Music"]
    assert updated["applications"]["allowlist"][0]["aliases"] == ["notes"]
    assert updated["text_to_speech"]["speaking_rate"] == 0.9
    assert updated["wake_word"]["resume_delay_seconds"] == 1.0
    assert updated["music"]["directories"] == ["Music"]
    assert updated["browser"]["web_access_enabled"] is True
    assert updated["applications"]["allow_discovered_applications"] is True
