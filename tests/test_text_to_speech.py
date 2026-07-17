import asyncio
import wave
from pathlib import Path

import pytest

from audio.text_to_speech import PiperError, PiperTextToSpeech, prepare_spoken_text
from config import TextToSpeechConfig


class FakePiper(PiperTextToSpeech):
    def __init__(self, output: Path) -> None:
        super().__init__(TextToSpeechConfig())
        self.output = output
        self.played = False

    async def _synthesize(self, text: str, language: str) -> Path:
        assert text == "Ahoj"
        assert language == "sk"
        return self.output

    def _play_wave(self, path: Path) -> None:
        assert path == self.output
        self.played = True


class InvokeRecordingPiper(PiperTextToSpeech):
    def __init__(self, tmp_path: Path) -> None:
        super().__init__(TextToSpeechConfig())
        self.executable = tmp_path / "piper.exe"
        self.voice = tmp_path / "voice.onnx"
        self.executable.touch()
        self.voice.touch()
        self.calls: list[tuple[list[str], str | None]] = []

    def _paths(self, language: str) -> tuple[Path, Path]:
        return self.executable, self.voice

    async def _invoke(self, arguments: list[str], input_text: str | None) -> tuple[int, str]:
        self.calls.append((arguments, input_text))
        output = Path(arguments[arguments.index("-f") + 1])
        output.write_bytes(b"wave")
        return 0, ""


def test_missing_piper_configuration_fails_closed() -> None:
    service = PiperTextToSpeech(TextToSpeechConfig())
    with pytest.raises(PiperError, match="executable"):
        service._paths("sk")


def test_speech_queue_runs_and_cleans_temporary_audio(tmp_path: Path) -> None:
    output = tmp_path / "speech.wav"
    with wave.open(str(output), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(16000)
        target.writeframes(b"\0\0" * 160)
    service = FakePiper(output)

    async def run() -> None:
        await service.speak("Ahoj", "sk")
        await service.close()

    asyncio.run(run())
    assert service.played
    assert not output.exists()


def test_spoken_text_removes_markup_and_is_bounded() -> None:
    config = TextToSpeechConfig(max_spoken_characters=80, max_spoken_sentences=2)
    text = "**Prvá veta.** Druhá veta s [odkazom](https://example.com). Tretia sa nečíta."
    spoken = prepare_spoken_text(text, config)
    assert spoken == "Prvá veta. Druhá veta s odkazom."
    assert len(spoken) <= 80


def test_spoken_text_does_not_read_code_or_windows_paths() -> None:
    config = TextToSpeechConfig(max_spoken_characters=300)
    spoken = prepare_spoken_text("Pozri C:\\Users\\matej\\secret.txt. ```python\nprint('x')\n```", config)
    assert "secret.txt" not in spoken
    assert "print" not in spoken


def test_spoken_text_normalizes_stylized_unicode() -> None:
    assert prepare_spoken_text("𝒔𝒍𝒐𝒘𝒆𝒅", TextToSpeechConfig()) == "slowed"


def test_english_code_note_uses_english() -> None:
    spoken = prepare_spoken_text("Result: ```python\nprint(1)\n```", TextToSpeechConfig(), "en")
    assert "Code details are in the text response" in spoken


def test_piper_prefers_unicode_safe_modern_cli(tmp_path: Path) -> None:
    async def run() -> None:
        service = InvokeRecordingPiper(tmp_path)
        output = await service._synthesize("Žltý kôň", "sk")
        try:
            arguments, stdin = service.calls[0]
            assert arguments[-2:] == ["--", "Žltý kôň"]
            assert stdin is None
        finally:
            output.unlink(missing_ok=True)

    asyncio.run(run())
