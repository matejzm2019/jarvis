from pathlib import Path

import pytest

from config import AllowedApplication, ApplicationConfig, FileConfig, JarvisConfig, MemoryConfig
from memory.storage import MemoryStore
from assistant.orchestrator import JarvisOrchestrator
from tools.applications import ApplicationCatalog
from tools.files import FileService


def test_sqlite_memory_is_bounded_and_clearable(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "jarvis.db", max_history=2)
    store.add_message("user", "one")
    store.add_message("assistant", "two")
    store.add_message("user", "three")
    assert [item["content"] for item in store.recent_messages(10)] == ["two", "three"]
    assert store.clear_history() == 2
    assert store.recent_messages(10) == []


def test_permanent_memory_rejects_secrets(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "jarvis.db")
    with pytest.raises(ValueError, match="cannot be stored"):
        store.remember_fact("My password is hunter2")
    assert store.facts() == []
    store.add_message("user", "My access token is abcdef123")
    assert store.recent_messages(10) == []


def test_preferences_facts_and_aliases_round_trip(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "jarvis.db")
    store.set_preference("language", "Slovak")
    store.remember_fact("Mám rád stručné odpovede")
    store.set_alias("application", "editor", "Visual Studio Code")
    assert store.preferences() == {"language": "Slovak"}
    assert store.facts()[0]["fact"] == "Mám rád stručné odpovede"
    assert store.aliases("application") == {"editor": "Visual Studio Code"}


def test_confirmed_aliases_resolve_only_to_safe_targets(tmp_path: Path) -> None:
    folder = tmp_path / "projects"
    folder.mkdir()
    store = MemoryStore(tmp_path / "jarvis.db")
    store.set_alias("folder", "projekty", str(folder))
    config = JarvisConfig(
        files=FileConfig(searchable_directories=[str(tmp_path)]),
        memory=MemoryConfig(database_path=str(tmp_path / "jarvis.db")),
        applications=ApplicationConfig(allowlist=[AllowedApplication(name="Visual Studio Code")]),
    )
    assert FileService(config, store).require("projekty", kind="folder") == folder
    store.set_alias("application", "editor", "Visual Studio Code")
    catalog = ApplicationCatalog(config.applications, lambda: store.aliases("application"))
    assert catalog._allowed("editor").name == "Visual Studio Code"


def test_permanent_memory_requires_explicit_request_text() -> None:
    assert JarvisOrchestrator._explicit_tool_request("remember_fact", "Zapamätaj si, že mám rád modrú.")
    assert not JarvisOrchestrator._explicit_tool_request("remember_fact", "Mám rád modrú.")
