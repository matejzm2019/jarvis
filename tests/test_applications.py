from pathlib import Path

import pytest

from config import AllowedApplication, ApplicationConfig
from tools.applications import ApplicationCatalog


def test_configured_executable_resolves(tmp_path: Path) -> None:
    executable = tmp_path / "safe-app.exe"
    executable.write_bytes(b"MZ")
    config = ApplicationConfig(
        allowlist=[AllowedApplication(name="Safe App", executable_path=str(executable), aliases=["safe"])]
    )
    target = ApplicationCatalog(config).resolve("safe")
    assert target.path == executable.resolve()
    assert target.source == "configured path"


def test_unlisted_application_is_rejected() -> None:
    catalog = ApplicationCatalog(
        ApplicationConfig(
            allowlist=[AllowedApplication(name="Notepad")],
            allow_discovered_applications=False,
        )
    )
    with pytest.raises(ValueError, match="allowlist"):
        catalog.resolve("definitely-unlisted-application")


def test_missing_configured_executable_fails(tmp_path: Path) -> None:
    catalog = ApplicationCatalog(
        ApplicationConfig(
            allowlist=[AllowedApplication(name="Missing", executable_path=str(tmp_path / "missing.exe"))]
        )
    )
    with pytest.raises(FileNotFoundError):
        catalog.resolve("Missing")


def test_discovers_steam_start_menu_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    shortcut = tmp_path / "Puck.url"
    shortcut.write_text("[InternetShortcut]\nURL=steam://rungameid/1", encoding="utf-8")
    monkeypatch.setattr(ApplicationCatalog, "_shortcut_candidates", staticmethod(lambda: [shortcut]))
    target = ApplicationCatalog(ApplicationConfig()).resolve("Puck")
    assert target.path == shortcut
    assert target.source == "Start Menu shortcut"


def test_discovers_game_from_steam_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    steamapps = tmp_path / "steamapps"
    steamapps.mkdir()
    (steamapps / "appmanifest_123.acf").write_text(
        '"AppState" { "appid" "123" "name" "Example Game" }', encoding="utf-8"
    )
    monkeypatch.setattr(ApplicationCatalog, "_shortcut_candidates", staticmethod(list))
    monkeypatch.setattr(ApplicationCatalog, "_steam_roots", staticmethod(lambda: [tmp_path]))
    target = ApplicationCatalog(ApplicationConfig()).resolve("Example Game")
    assert target.uri == "steam://rungameid/123"
    assert target.source == "Steam library"
