import asyncio

import numpy as np

from assistant.state import AssistantState, AssistantStatus
from assistant.voice_runtime import VoiceAssistantRuntime, response_language
from audio.recorder import AudioRecording
from audio.speech_to_text import Transcription
from config import JarvisConfig


class FakeAssistant:
    def __init__(self) -> None:
        self.state = AssistantState()
        self.requests: list[str] = []

    async def ask(self, text: str) -> str:
        self.requests.append(text)
        return "Rozumiem."


class FakeRecorder:
    async def record(self, cancel: asyncio.Event) -> AudioRecording:
        assert not cancel.is_set()
        return AudioRecording(np.ones(1600, dtype=np.float32), 16000)


class FakeTranscriber:
    def __init__(self, text: str) -> None:
        self.text = text

    async def transcribe(self, recording: AudioRecording) -> Transcription:
        return Transcription(self.text, "sk", 1.0, recording.duration_seconds)


class FakeSpeaker:
    def __init__(self) -> None:
        self.spoken: list[tuple[str, str]] = []

    async def start(self) -> None: pass
    async def stop(self) -> None: pass
    async def close(self) -> None: pass

    async def speak(self, text: str, language: str) -> None:
        self.spoken.append((text, language))


def test_voice_activation_runs_local_pipeline() -> None:
    async def run() -> None:
        assistant = FakeAssistant()
        speaker = FakeSpeaker()
        runtime = VoiceAssistantRuntime(
            JarvisConfig(), assistant, FakeRecorder(), FakeTranscriber("Ahoj"), speaker
        )
        await runtime.activate()
        assert runtime._speech_task is not None
        await runtime._speech_task
        assert assistant.requests == ["Ahoj"]
        assert speaker.spoken == [("Rozumiem.", "sk")]
        assert assistant.state.status is AssistantStatus.SLEEPING
        await runtime.close()

    asyncio.run(run())


def test_response_language_prefers_slovak_answer() -> None:
    assert response_language("Áno, toto je slovenská odpoveď.", "en") == "sk"
    assert response_language("This is an English answer.", "en") == "en"


def test_wake_listener_hooks_wrap_speech_for_barge_in() -> None:
    async def run() -> None:
        events: list[str] = []

        async def before() -> None:
            events.append("pause")

        async def during() -> None:
            events.append("barge-in")

        async def after() -> None:
            events.append("resume")

        runtime = VoiceAssistantRuntime(
            JarvisConfig(), FakeAssistant(), FakeRecorder(), FakeTranscriber("Ahoj"), FakeSpeaker(),
            before_activation=before, during_speech=during, after_activation=after,
        )
        await runtime.activate()
        await runtime._speech_task
        assert events == ["pause", "barge-in", "pause", "resume"]
        await runtime.close()

    asyncio.run(run())


def test_activation_during_speech_schedules_barge_in() -> None:
    async def run() -> None:
        runtime = VoiceAssistantRuntime(
            JarvisConfig(), FakeAssistant(), FakeRecorder(), FakeTranscriber("Ahoj"), FakeSpeaker()
        )
        called = asyncio.Event()

        async def activate() -> None:
            called.set()

        runtime.activate = activate  # type: ignore[method-assign]
        runtime._speech_task = asyncio.create_task(asyncio.sleep(10))
        runtime._schedule_activation()
        await asyncio.wait_for(called.wait(), 1)
        assert runtime._activation_task and runtime._activation_task.get_name() == "jarvis-voice-barge-in"
        runtime._speech_task.cancel()
        await asyncio.gather(runtime._speech_task, return_exceptions=True)

    asyncio.run(run())


def test_stop_phrase_does_not_call_model() -> None:
    async def run() -> None:
        assistant = FakeAssistant()
        speaker = FakeSpeaker()
        runtime = VoiceAssistantRuntime(
            JarvisConfig(), assistant, FakeRecorder(), FakeTranscriber("prestaň"), speaker
        )
        await runtime.activate()
        assert assistant.requests == []
        assert speaker.spoken == []
        await runtime.close()

    asyncio.run(run())
