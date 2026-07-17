from pathlib import Path

import pytest

from config import JarvisConfig, MusicConfig
from tools.music import MusicLibrary


def test_local_music_search_is_bounded_to_configured_root(tmp_path: Path) -> None:
    music = tmp_path / "music"
    music.mkdir()
    (music / "My Favorite Song.mp3").write_bytes(b"audio")
    (music / "notes.txt").write_text("not audio", encoding="utf-8")
    library = MusicLibrary(JarvisConfig(music=MusicConfig(directories=[str(music)])))
    assert [item["name"] for item in library.search("favorite", 10)] == ["My Favorite Song.mp3"]


def test_local_music_rejects_files_outside_root(tmp_path: Path) -> None:
    music = tmp_path / "music"
    music.mkdir()
    outside = tmp_path / "outside.mp3"
    outside.write_bytes(b"audio")
    library = MusicLibrary(JarvisConfig(music=MusicConfig(directories=[str(music)])))
    with pytest.raises(PermissionError):
        library.play(str(outside))
