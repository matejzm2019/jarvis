from pathlib import Path

import pytest
from pydantic import ValidationError

from config import JarvisConfig, OllamaConfig, load_config


def test_load_minimal_config(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("ollama:\n  model: gemma64\n", encoding="utf-8")
    config = load_config(path)
    assert config.ollama.model == "gemma64"
    assert config.ollama.context_size == 65536
    assert config.files.searchable_directories == ["Desktop", "Documents", "Downloads", "Music"]


def test_rejects_non_local_ollama() -> None:
    with pytest.raises(ValidationError, match="loopback"):
        OllamaConfig(base_url="https://example.com", model="gemma64")


def test_resolves_explicit_search_root(tmp_path: Path) -> None:
    config = JarvisConfig.model_validate({"files": {"searchable_directories": [str(tmp_path)]}})
    assert config.searchable_paths() == [tmp_path.resolve()]


def test_rejects_duplicate_voice_hotkeys() -> None:
    with pytest.raises(ValidationError, match="must be different"):
        JarvisConfig.model_validate(
            {"hotkeys": {"push_to_talk": "ctrl+alt+x", "stop_speaking": "CTRL+ALT+X"}}
        )
