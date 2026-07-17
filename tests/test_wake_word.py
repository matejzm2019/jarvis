import threading

import numpy as np
import pytest

from audio.wake_word import WakeWordDetector, WakeWordError
from config import AudioConfig, WakeWordConfig


class FakeModel:
    def reset(self) -> None:
        pass

    def predict(self, frame: np.ndarray) -> dict[str, float]:
        assert frame.dtype == np.int16
        return {"hey_jarvis": 0.9}


class FakeStream:
    def __init__(self, **kwargs: object) -> None:
        self.callback = kwargs["callback"]
        self.started = False
        self.closed = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def close(self) -> None:
        self.closed = True


def _model_files(tmp_path):
    for name in ("melspectrogram.onnx", "embedding_model.onnx", "hey_jarvis_v0.1.onnx"):
        (tmp_path / name).write_bytes(b"model")
    return tmp_path / "hey_jarvis_v0.1.onnx"


def test_wake_word_detects_threshold_crossing(tmp_path) -> None:
    detected = threading.Event()
    stream: FakeStream | None = None

    def stream_factory(**kwargs: object) -> FakeStream:
        nonlocal stream
        stream = FakeStream(**kwargs)
        return stream

    detector = WakeWordDetector(
        WakeWordConfig(model_path=str(_model_files(tmp_path)), sensitivity=0.5),
        AudioConfig(),
        lambda score: detected.set() if score >= 0.5 else None,
        model_factory=lambda **_: FakeModel(),
        stream_factory=stream_factory,
    )
    detector.start()
    assert stream is not None and stream.started
    stream.callback(np.ones((1280, 1), dtype=np.int16), 1280, None, None)
    assert detected.wait(1)
    detector.stop()
    assert stream.closed
    assert not detector.is_running


def test_wake_word_missing_models_fails_closed(tmp_path) -> None:
    detector = WakeWordDetector(
        WakeWordConfig(model_path=str(tmp_path / "hey_jarvis_v0.1.onnx")),
        AudioConfig(),
        lambda _: None,
        model_factory=lambda **_: FakeModel(),
        stream_factory=lambda **kwargs: FakeStream(**kwargs),
    )
    with pytest.raises(WakeWordError, match="Missing wake-word assets"):
        detector.start()
