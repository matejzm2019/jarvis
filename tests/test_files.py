from pathlib import Path

import pytest

from config import JarvisConfig
from tools.files import FileService


def make_service(root: Path) -> FileService:
    config = JarvisConfig.model_validate({"files": {"searchable_directories": [str(root)]}})
    return FileService(config)


def test_search_is_confined_to_configured_root(tmp_path: Path) -> None:
    (tmp_path / "report-final.txt").write_text("local", encoding="utf-8")
    service = make_service(tmp_path)
    results = service.search("report", folders=False, max_results=10)
    assert [item["name"] for item in results] == ["report-final.txt"]


def test_sensitive_directory_is_pruned(tmp_path: Path) -> None:
    secret_dir = tmp_path / ".ssh"
    secret_dir.mkdir()
    (secret_dir / "id_rsa").write_text("secret", encoding="utf-8")
    service = make_service(tmp_path)
    assert service.search("id_rsa", folders=False, max_results=10) == []


def test_outside_path_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "allowed"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("no", encoding="utf-8")
    with pytest.raises(PermissionError):
        make_service(root).policy.require(str(outside), kind="file")


def test_read_supported_text_is_bounded(tmp_path: Path) -> None:
    path = tmp_path / "notes.md"
    path.write_text("hello", encoding="utf-8")
    content, truncated, redacted = make_service(tmp_path).read(str(path))
    assert content == "hello"
    assert not truncated
    assert not redacted


def test_read_redacts_credentials_before_model_context(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text('api_key = "super-secret-value"\npublic = yes', encoding="utf-8")
    content, _, redacted = make_service(tmp_path).read(str(path))
    assert "super-secret-value" not in content
    assert "[REDACTED]" in content
    assert redacted
