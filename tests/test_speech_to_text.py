import asyncio
from types import SimpleNamespace

import numpy as np

from audio.recorder import AudioRecording
from audio.speech_to_text import FasterWhisperTranscriber
from config import SpeechToTextConfig


class FakeModel:
    def transcribe(self, samples: np.ndarray, **kwargs: object):
        assert samples.dtype == np.float32
        assert kwargs["language"] is None
        return [SimpleNamespace(text=" Ahoj "), SimpleNamespace(text="svet")], SimpleNamespace(
            language="sk", language_probability=0.98, duration=1.0
        )


def test_transcribes_in_memory_with_offline_cpu_defaults() -> None:
    factory_arguments: dict[str, object] = {}

    def factory(model: str, **kwargs: object) -> FakeModel:
        factory_arguments["model"] = model
        factory_arguments.update(kwargs)
        return FakeModel()

    service = FasterWhisperTranscriber(SpeechToTextConfig(model="medium"), factory)
    recording = AudioRecording(np.ones(16000, dtype=np.float32), 16000)
    result = asyncio.run(service.transcribe(recording))
    assert result.text == "Ahoj svet"
    assert result.language == "sk"
    assert factory_arguments["device"] == "cpu"
    assert factory_arguments["compute_type"] == "int8"
    assert factory_arguments["local_files_only"] is True

