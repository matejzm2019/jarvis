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
        ApplicationConfig(allowlist=[AllowedApplication(name="Notepad")])
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

