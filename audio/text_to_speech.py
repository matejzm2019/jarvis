"""Queued local Piper synthesis and interruptible audio playback."""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import tempfile
import threading
import unicodedata
import wave
from dataclasses import dataclass
from pathlib import Path

from config import TextToSpeechConfig, load_config


_FENCED_CODE = re.compile(r"```.*?```", re.DOTALL)
_MARKDOWN_LINK = re.compile(r"\[([^]]+)]\([^)]*\)")
_URL = re.compile(r"https?://\S+", re.IGNORECASE)
_WINDOWS_PATH = re.compile(r"(?<!\w)[A-Za-z]:\\(?:[^\s,;]+\\)*[^\s,;]+")
_SENTENCE = re.compile(r".+?(?:[.!?](?=\s|$)|$)", re.DOTALL)


def prepare_spoken_text(text: str, config: TextToSpeechConfig, language: str = "sk") -> str:
    """Turn a rich text answer into short, pronounceable Piper input."""
    value = unicodedata.normalize("NFKC", text)
    code_note = (
        " Code details are in the text response. "
        if language.casefold().startswith("en")
        else " Podrobnosti kódu sú v textovej odpovedi. "
    )
    value = _FENCED_CODE.sub(code_note, value)
    value = _MARKDOWN_LINK.sub(r"\1", value)
    value = _URL.sub("odkaz", value)
    value = _WINDOWS_PATH.sub("cesta uvedená v textovej odpovedi", value)
    value = re.sub(r"[`*_#>|~]", " ", value)
    value = re.sub(r"^\s*[-+]\s+", "", value, flags=re.MULTILINE)
    value = re.sub(r"\s+", " ", value).strip()
    sentences = [part.strip() for part in _SENTENCE.findall(value) if part.strip()]
    value = " ".join(sentences[: config.max_spoken_sentences])
    if len(value) > config.max_spoken_characters:
        value = value[: config.max_spoken_characters + 1].rsplit(" ", 1)[0].rstrip(" ,;:-")
        if value and value[-1] not in ".!?":
            value += "."
    return value


class PiperError(RuntimeError):
    """Piper configuration, synthesis, or playback failure."""


class SpeechInterruptedError(PiperError):
    pass


@dataclass(slots=True)
class _SpeechRequest:
    text: str
    language: str
    future: asyncio.Future[None]


class PiperTextToSpeech:
    """Serialize Piper speech requests and allow immediate local interruption."""

    def __init__(self, config: TextToSpeechConfig) -> None:
        self.config = config
        self._queue: asyncio.Queue[_SpeechRequest | None] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._playback_stop = threading.Event()

    def _paths(self, language: str) -> tuple[Path, Path]:
        executable = Path(self.config.executable_path).expanduser().resolve(strict=False)
        voice_value = (
            self.config.english_voice_model_path
            if language.casefold().startswith("en") and self.config.english_voice_model_path
            else self.config.voice_model_path
        )
        voice = Path(voice_value).expanduser().resolve(strict=False)
        if not executable.is_file():
            raise PiperError("Piper executable_path is not configured or does not exist")
        if not voice.is_file() or voice.suffix.casefold() != ".onnx":
            raise PiperError(f"Piper voice for language '{language}' is not configured or is not an ONNX file")
        return executable, voice

    async def start(self) -> None:
        """Start the speech queue without launching Piper yet."""
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._run_queue(), name="jarvis-piper-queue")

    async def speak(self, text: str, language: str = "sk") -> None:
        """Queue text and wait until it is spoken or interrupted."""
        value = prepare_spoken_text(text, self.config, language)
        if not value:
            return
        await self.start()
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        await self._queue.put(_SpeechRequest(value, language, future))
        await future

    async def stop(self) -> None:
        """Stop synthesis/playback and reject queued speech without killing the worker."""
        self._playback_stop.set()
        process = self._process
        if process and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=2)
            except TimeoutError:
                process.kill()
                await process.wait()
        while True:
            try:
                request = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if request and not request.future.done():
                request.future.set_exception(SpeechInterruptedError("Speech was interrupted"))

    async def close(self) -> None:
        """Interrupt speech and shut down the queue worker."""
        await self.stop()
        if self._worker and not self._worker.done():
            await self._queue.put(None)
            await self._worker
        self._worker = None

    async def _run_queue(self) -> None:
        while True:
            request = await self._queue.get()
            if request is None:
                return
            output: Path | None = None
            self._playback_stop.clear()
            try:
                output = await self._synthesize(request.text, request.language)
                if self._playback_stop.is_set():
                    raise SpeechInterruptedError("Speech was interrupted")
                await asyncio.to_thread(self._play_wave, output)
                if self._playback_stop.is_set():
                    raise SpeechInterruptedError("Speech was interrupted")
            except Exception as exc:
                if not request.future.done():
                    request.future.set_exception(exc)
            else:
                if not request.future.done():
                    request.future.set_result(None)
            finally:
                if output:
                    output.unlink(missing_ok=True)

    async def _invoke(self, arguments: list[str], input_text: str | None) -> tuple[int, str]:
        kwargs = {"creationflags": 0x08000000} if os.name == "nt" else {}
        environment = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
        process = await asyncio.create_subprocess_exec(
            *arguments,
            stdin=asyncio.subprocess.PIPE if input_text is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
            env=environment,
            **kwargs,
        )
        self._process = process
        try:
            _, stderr = await process.communicate(
                input_text.encode("utf-8") if input_text is not None else None
            )
        finally:
            self._process = None
        return process.returncode or 0, stderr.decode("utf-8", errors="replace")[:4000]

    async def _synthesize(self, text: str, language: str) -> Path:
        executable, voice = self._paths(language)
        handle, name = tempfile.mkstemp(prefix="jarvis-piper-", suffix=".wav")
        os.close(handle)
        output = Path(name)
        output.unlink(missing_ok=True)
        length_scale = str(round(1 / self.config.speaking_rate, 4))
        modern = [
            str(executable), "-m", str(voice), "-f", str(output),
            "--length-scale", length_scale, "--", text,
        ]
        code, error = await self._invoke(modern, None)
        if code and not self._playback_stop.is_set():
            legacy = [
                str(executable), "--model", str(voice), "--output_file", str(output),
                "--length_scale", length_scale,
            ]
            code, legacy_error = await self._invoke(legacy, text)
            error = legacy_error or error
        if self._playback_stop.is_set():
            output.unlink(missing_ok=True)
            raise SpeechInterruptedError("Speech was interrupted")
        if code or not output.is_file() or output.stat().st_size == 0:
            output.unlink(missing_ok=True)
            raise PiperError(f"Piper synthesis failed: {error.strip() or f'exit code {code}'}")
        return output

    def _play_wave(self, path: Path) -> None:
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise PiperError("sounddevice is not installed") from exc
        with wave.open(str(path), "rb") as source:
            if source.getsampwidth() != 2:
                raise PiperError("Piper produced unsupported audio; expected 16-bit PCM WAV")
            with sd.RawOutputStream(
                samplerate=source.getframerate(),
                channels=source.getnchannels(),
                dtype="int16",
                device=self.config.output_device,
            ) as output:
                frames_per_chunk = max(1, source.getframerate() // 20)
                while not self._playback_stop.is_set():
                    data = source.readframes(frames_per_chunk)
                    if not data:
                        break
                    output.write(data)


async def _test_speech(text: str, language: str, config_path: str) -> None:
    service = PiperTextToSpeech(load_config(config_path).text_to_speech)
    try:
        await service.speak(text, language)
    finally:
        await service.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Test the configured local Piper voice")
    parser.add_argument("--text", required=True)
    parser.add_argument("--language", choices=("sk", "en"), default="sk")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()
    asyncio.run(_test_speech(args.text, args.language, args.config))


if __name__ == "__main__":
    main()
