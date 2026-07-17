"""Local faster-whisper transcription with offline-by-default model loading."""

from __future__ import annotations

import argparse
import asyncio
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audio.recorder import AudioRecording
from config import SpeechToTextConfig, load_config


class SpeechToTextError(RuntimeError):
    """Local model loading or transcription failure."""


@dataclass(frozen=True, slots=True)
class Transcription:
    """Text and locally detected language metadata."""

    text: str
    language: str
    language_probability: float
    duration_seconds: float


class FasterWhisperTranscriber:
    """Lazily load one local Whisper model and serialize native inference."""

    def __init__(
        self,
        config: SpeechToTextConfig,
        model_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.config = config
        self._model_factory = model_factory
        self._model: Any | None = None
        self._model_lock = threading.Lock()
        self._inference_lock = threading.Lock()

    @property
    def device(self) -> str:
        """Resolve `auto` safely for the Windows AMD target."""
        return "cpu" if self.config.device == "auto" else self.config.device

    @property
    def compute_type(self) -> str:
        """Resolve the CTranslate2 compute type for the selected device."""
        if self.config.compute_type != "auto":
            return self.config.compute_type
        return "int8" if self.device == "cpu" else "float16"

    def _load_model(self) -> Any:
        with self._model_lock:
            if self._model is not None:
                return self._model
            try:
                model_value = self.config.model
                local_path = Path(model_value).expanduser()
                if local_path.is_dir():
                    required = ("model.bin", "config.json", "tokenizer.json")
                    missing = [name for name in required if not (local_path / name).is_file()]
                    if missing:
                        raise ValueError(
                            f"Local Whisper directory is incomplete; missing: {', '.join(missing)}"
                        )
                    model_value = str(local_path.resolve())
                if self._model_factory is None:
                    from faster_whisper import WhisperModel

                    factory: Callable[..., Any] = WhisperModel
                else:
                    factory = self._model_factory
                self._model = factory(
                    model_value,
                    device=self.device,
                    compute_type=self.compute_type,
                    cpu_threads=self.config.cpu_threads,
                    local_files_only=not self.config.allow_model_download,
                )
            except Exception as exc:
                command = (
                    ".\\.venv\\Scripts\\python.exe -m audio.speech_to_text "
                    f"--download-model {self.config.model}"
                )
                raise SpeechToTextError(
                    f"Could not load local faster-whisper model '{self.config.model}'. "
                    f"Download it explicitly with: {command}. Cause: {exc}"
                ) from exc
            return self._model

    async def transcribe(self, recording: AudioRecording) -> Transcription:
        """Transcribe an in-memory mono recording without writing raw audio."""
        if recording.samples.size == 0:
            raise SpeechToTextError("Cannot transcribe an empty recording")

        def run() -> Transcription:
            with self._inference_lock:
                model = self._load_model()
                language = None if self.config.language == "auto" else self.config.language
                try:
                    segments, info = model.transcribe(
                        recording.samples,
                        language=language,
                        beam_size=self.config.beam_size,
                        condition_on_previous_text=False,
                        vad_filter=False,
                    )
                    text = " ".join(str(segment.text).strip() for segment in segments).strip()
                except Exception as exc:
                    raise SpeechToTextError(f"Local transcription failed: {exc}") from exc
                return Transcription(
                    text=text,
                    language=str(getattr(info, "language", language or "unknown")),
                    language_probability=float(getattr(info, "language_probability", 0.0)),
                    duration_seconds=float(getattr(info, "duration", recording.duration_seconds)),
                )

        return await asyncio.to_thread(run)


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage the explicitly configured faster-whisper model")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check-model", action="store_true")
    action.add_argument("--download-model", metavar="MODEL")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()
    from faster_whisper.utils import download_model

    model = args.download_model or load_config(Path(args.config)).speech_to_text.model
    try:
        path = download_model(model, local_files_only=args.check_model)
    except Exception as exc:
        raise SystemExit(f"Whisper model '{model}' is not available locally: {exc}") from exc
    print(path)


if __name__ == "__main__":
    main()
