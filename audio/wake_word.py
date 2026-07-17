"""Continuous local wake-word detection using openWakeWord and ONNX."""

from __future__ import annotations

import argparse
import logging
import os
import queue
import shutil
import threading
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from config import AudioConfig, WakeWordConfig, load_config
from utils.paths import PROJECT_ROOT

MODEL_FILES = ("melspectrogram.onnx", "embedding_model.onnx", "hey_jarvis_v0.1.onnx")
MODEL_RELEASE_URL = "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1"


class WakeWordError(RuntimeError):
    """Wake-word model, microphone, or inference failure."""


def resolve_model_path(value: str) -> Path:
    """Resolve a configured wake model relative to the Jarvis project."""
    path = Path(value).expanduser()
    return (path if path.is_absolute() else PROJECT_ROOT / path).resolve(strict=False)


def required_model_files(model_path: Path) -> tuple[Path, Path, Path]:
    """Return the wake and shared openWakeWord ONNX assets."""
    directory = model_path.parent
    return directory / "melspectrogram.onnx", directory / "embedding_model.onnx", model_path


def check_model_files(model_path: Path) -> list[Path]:
    """Return missing local files without attempting a network download."""
    return [path for path in required_model_files(model_path) if not path.is_file()]


def download_model_files(target_directory: Path) -> tuple[Path, ...]:
    """Explicitly download only the three ONNX assets required for Hey Jarvis."""
    target_directory.mkdir(parents=True, exist_ok=True)
    downloaded: list[Path] = []
    for name in MODEL_FILES:
        target = target_directory / name
        if target.is_file() and target.stat().st_size:
            downloaded.append(target)
            continue
        partial = target.with_suffix(target.suffix + ".part")
        request = urllib.request.Request(
            f"{MODEL_RELEASE_URL}/{name}", headers={"User-Agent": "Jarvis-local-installer/0.3"}
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as source, partial.open("wb") as output:
                shutil.copyfileobj(source, output)
            if partial.stat().st_size == 0:
                raise WakeWordError(f"Downloaded wake-word asset is empty: {name}")
            os.replace(partial, target)
        except Exception as exc:
            partial.unlink(missing_ok=True)
            raise WakeWordError(f"Could not download {name}: {exc}") from exc
        downloaded.append(target)
    return tuple(downloaded)


class WakeWordDetector:
    """Process 16 kHz microphone frames locally without retaining raw audio."""

    def __init__(
        self,
        config: WakeWordConfig,
        audio: AudioConfig,
        on_detect: Callable[[float], None],
        *,
        model_factory: Callable[..., Any] | None = None,
        stream_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.config = config
        self.audio = audio
        self.on_detect = on_detect
        self._model_factory = model_factory
        self._stream_factory = stream_factory
        self._model: Any | None = None
        self._stream: Any | None = None
        self._frames: queue.Queue[np.ndarray | None] = queue.Queue(maxsize=8)
        self._worker: threading.Thread | None = None
        self._stop = threading.Event()
        self._last_detection = 0.0
        self._lock = threading.RLock()
        self.log = logging.getLogger("jarvis.audio.wake_word")

    @property
    def is_running(self) -> bool:
        """Whether the microphone stream and inference worker are active."""
        with self._lock:
            return bool(self._worker and self._worker.is_alive())

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model
        model_path = resolve_model_path(self.config.model_path)
        missing = check_model_files(model_path)
        if missing:
            command = ".\\.venv\\Scripts\\python.exe -m audio.wake_word --download-model"
            names = ", ".join(path.name for path in missing)
            raise WakeWordError(f"Missing wake-word assets: {names}. Run: {command}")
        if self._model_factory is None:
            try:
                from openwakeword.model import Model
            except ImportError as exc:
                raise WakeWordError("openWakeWord is not installed") from exc
            factory: Callable[..., Any] = Model
        else:
            factory = self._model_factory
        melspec, embedding, wake = required_model_files(model_path)
        try:
            self._model = factory(
                wakeword_models=[str(wake)],
                inference_framework="onnx",
                melspec_model_path=str(melspec),
                embedding_model_path=str(embedding),
            )
        except Exception as exc:
            raise WakeWordError(f"Could not load local wake-word model: {exc}") from exc
        return self._model

    def start(self) -> None:
        """Start wake listening; repeated calls are harmless."""
        if self.is_running:
            return
        model = self._load_model()
        model.reset()
        self._stop.clear()
        while not self._frames.empty():
            try:
                self._frames.get_nowait()
            except queue.Empty:
                break
        if self._stream_factory is None:
            try:
                import sounddevice as sd
            except ImportError as exc:
                raise WakeWordError("sounddevice is not installed") from exc
            stream_factory: Callable[..., Any] = sd.InputStream
        else:
            stream_factory = self._stream_factory
        self._worker = threading.Thread(target=self._run, name="jarvis-wake-word", daemon=True)
        self._worker.start()
        try:
            self._stream = stream_factory(
                samplerate=16000,
                blocksize=1280,
                channels=1,
                dtype="int16",
                device=self.audio.microphone_device,
                callback=self._audio_callback,
            )
            self._stream.start()
        except Exception as exc:
            self._stop.set()
            self._frames.put(None)
            self._worker.join(timeout=3)
            self._worker = None
            self._stream = None
            raise WakeWordError(f"Could not start wake-word microphone stream: {exc}") from exc

    def _audio_callback(self, data: np.ndarray, frames: int, timing: Any, status: Any) -> None:
        del frames, timing
        if status:
            self.log.warning("Wake-word audio status: %s", status)
        frame = np.asarray(data[:, 0], dtype=np.int16).copy()
        try:
            self._frames.put_nowait(frame)
        except queue.Full:
            try:
                self._frames.get_nowait()
            except queue.Empty:
                pass
            try:
                self._frames.put_nowait(frame)
            except queue.Full:
                pass

    @staticmethod
    def _highest_score(predictions: dict[str, Any]) -> float:
        scores = [float(np.max(value)) for value in predictions.values()]
        return max(scores, default=0.0)

    def _run(self) -> None:
        model = self._model
        assert model is not None
        while not self._stop.is_set():
            try:
                frame = self._frames.get(timeout=0.25)
            except queue.Empty:
                continue
            if frame is None:
                return
            try:
                score = self._highest_score(model.predict(frame))
            except Exception:
                self.log.exception("Wake-word inference failed")
                continue
            now = time.monotonic()
            if score < self.config.sensitivity or now - self._last_detection < self.config.cooldown_seconds:
                continue
            self._last_detection = now
            model.reset()
            try:
                self.on_detect(score)
            except Exception:
                self.log.exception("Wake-word callback failed")

    def stop(self) -> None:
        """Stop listening and release the microphone while keeping models warm."""
        with self._lock:
            self._stop.set()
            stream, worker = self._stream, self._worker
            self._stream = None
            self._worker = None
        if stream is not None:
            try:
                stream.stop()
            finally:
                stream.close()
        try:
            self._frames.put_nowait(None)
        except queue.Full:
            pass
        if worker and worker is not threading.current_thread():
            worker.join(timeout=3)


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage the local Hey Jarvis openWakeWord model")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check-model", action="store_true")
    action.add_argument("--download-model", action="store_true")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()
    config = load_config(args.config)
    model_path = resolve_model_path(config.wake_word.model_path)
    if args.download_model:
        for path in download_model_files(model_path.parent):
            print(path)
        return
    missing = check_model_files(model_path)
    if missing:
        raise SystemExit("Missing wake-word assets: " + ", ".join(path.name for path in missing))
    for path in required_model_files(model_path):
        print(path)


if __name__ == "__main__":
    main()
