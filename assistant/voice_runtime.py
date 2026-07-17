"""Push-to-talk and wake-activated local voice pipeline."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable

from assistant.orchestrator import JarvisOrchestrator
from assistant.state import AssistantStatus
from audio.interruption import GlobalHotkeyManager
from audio.recorder import AudioError, AudioRecorder, NoSpeechDetected
from audio.speech_to_text import FasterWhisperTranscriber, SpeechToTextError
from audio.text_to_speech import PiperError, PiperTextToSpeech, SpeechInterruptedError
from config import JarvisConfig

STOP_PHRASES = {"stop", "stop speaking", "prestaň", "ticho", "buď ticho"}
ActivationHook = Callable[[], Awaitable[None] | None]

_SLOVAK_MARKERS = re.compile(r"[áäčďéíĺľňóôŕšťúýž]", re.IGNORECASE)
_SLOVAK_WORDS = {
    "a", "aby", "ale", "áno", "čo", "ďakujem", "je", "nie", "pre", "prosím",
    "som", "sú", "tento", "to", "v", "z", "že",
}


def response_language(text: str, fallback: str = "sk") -> str:
    """Choose the Piper voice from the answer instead of unreliable input detection."""
    if _SLOVAK_MARKERS.search(text):
        return "sk"
    words = set(re.findall(r"[^\W\d_]+", text.casefold(), re.UNICODE))
    if len(words & _SLOVAK_WORDS) >= 2:
        return "sk"
    return "en" if fallback.casefold().startswith("en") else "sk"


class VoiceAssistantRuntime:
    """Run activated audio locally without continuous microphone capture."""

    def __init__(
        self,
        config: JarvisConfig,
        assistant: JarvisOrchestrator,
        recorder: AudioRecorder | None = None,
        transcriber: FasterWhisperTranscriber | None = None,
        speaker: PiperTextToSpeech | None = None,
        *,
        before_activation: ActivationHook | None = None,
        during_speech: ActivationHook | None = None,
        after_activation: ActivationHook | None = None,
    ) -> None:
        self.config = config
        self.assistant = assistant
        self.recorder = recorder or AudioRecorder(config.audio, config.speech_to_text)
        self.transcriber = transcriber or FasterWhisperTranscriber(config.speech_to_text)
        self.speaker = speaker or PiperTextToSpeech(config.text_to_speech)
        self.before_activation = before_activation
        self.during_speech = during_speech
        self.after_activation = after_activation
        self.hotkeys: GlobalHotkeyManager | None = None
        self._activation_lock = asyncio.Lock()
        self._record_cancel = asyncio.Event()
        self._activation_task: asyncio.Task[None] | None = None
        self._speech_task: asyncio.Task[None] | None = None
        self._shutdown = asyncio.Event()
        self._muted = False
        self.log = logging.getLogger("jarvis.voice")

    async def start(self) -> None:
        """Register native hotkeys; microphone remains closed until activation."""
        loop = asyncio.get_running_loop()
        await self.speaker.start()
        self.hotkeys = GlobalHotkeyManager(
            {
                self.config.hotkeys.push_to_talk: lambda: loop.call_soon_threadsafe(self._schedule_activation),
                self.config.hotkeys.stop_speaking: lambda: loop.call_soon_threadsafe(self._schedule_stop),
            }
        )
        self.hotkeys.start()

    async def run_forever(self) -> None:
        """Run hotkey-driven voice mode until shutdown or cancellation."""
        await self.start()
        print(
            "Jarvis voice mode ready. "
            f"Push to talk: {self.config.hotkeys.push_to_talk}; "
            f"stop speech: {self.config.hotkeys.stop_speaking}. Press Ctrl+C to exit."
        )
        try:
            await self._shutdown.wait()
        finally:
            await self.close()

    def request_shutdown(self) -> None:
        """Request an orderly voice runtime shutdown."""
        self._shutdown.set()

    def _schedule_activation(self) -> None:
        speech = self._speech_task
        if speech and not speech.done():
            self._activation_task = asyncio.create_task(self.activate(), name="jarvis-voice-barge-in")
            self._activation_task.add_done_callback(self._consume_task)
            return
        task = self._activation_task
        if task and not task.done():
            self._record_cancel.set()
            task.cancel()
            return
        self._activation_task = asyncio.create_task(self.activate(), name="jarvis-voice-activation")
        self._activation_task.add_done_callback(self._consume_task)

    def request_activation(self) -> None:
        """Schedule push-to-talk activation from the owning event-loop thread."""
        self._schedule_activation()

    def _schedule_stop(self) -> None:
        asyncio.create_task(self.stop_current(), name="jarvis-stop-speech")

    def _consume_task(self, task: asyncio.Task[None]) -> None:
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception:
            self.log.exception("Voice activation failed")

    async def stop_current(self) -> None:
        """Cancel active listening/thinking and stop queued or playing speech."""
        self._record_cancel.set()
        task = self._activation_task
        current = asyncio.current_task()
        if task and task is not current and not task.done():
            task.cancel()
        await self.stop_speaking()
        self.assistant.state.set(self._idle_status)

    async def stop_speaking(self) -> None:
        await self.speaker.stop()
        task = self._speech_task
        if task and task is not asyncio.current_task() and not task.done():
            await asyncio.gather(task, return_exceptions=True)

    @property
    def muted(self) -> bool:
        """Whether local speech output is muted."""
        return self._muted

    @property
    def _idle_status(self) -> AssistantStatus:
        return AssistantStatus.MUTED if self._muted else AssistantStatus.SLEEPING

    async def set_muted(self, muted: bool) -> None:
        """Mute or unmute local speech without disabling wake listening."""
        self._muted = muted
        if muted:
            await self.stop_speaking()
        self.assistant.state.set(self._idle_status)

    @staticmethod
    async def _call_hook(hook: ActivationHook | None) -> None:
        if hook is None:
            return
        result = hook()
        if result is not None:
            await result

    async def activate(self) -> None:
        """Record, transcribe, answer, and queue local speech for one activation."""
        await self.stop_speaking()
        if self._activation_lock.locked():
            return
        async with self._activation_lock:
            speech_owns_cleanup = False
            self._record_cancel.clear()
            try:
                await self._call_hook(self.before_activation)
                self.assistant.state.set(AssistantStatus.LISTENING)
                recording = await self.recorder.record(self._record_cancel)
                self.assistant.state.set(AssistantStatus.TRANSCRIBING)
                transcription = await self.transcriber.transcribe(recording)
                text = transcription.text.strip()
                if not text:
                    self.assistant.state.set(self._idle_status)
                    return
                print(f"You: {text}")
                normalized = text.casefold().strip(" .,!?:;")
                if normalized in STOP_PHRASES:
                    await self.stop_speaking()
                    self.assistant.state.set(self._idle_status)
                    return
                answer = await self.assistant.ask(text)
                print(f"Jarvis: {answer}")
                if self._muted:
                    self.assistant.state.set(self._idle_status)
                    return
                self._speech_task = asyncio.create_task(
                    self._speak(answer, response_language(answer, transcription.language)),
                    name="jarvis-speech",
                )
                speech_owns_cleanup = True
            except NoSpeechDetected:
                self.log.info("Activation ended without detected speech")
                self.assistant.state.set(self._idle_status)
            except (AudioError, SpeechToTextError) as exc:
                self.log.error("Voice input failed: %s", exc)
                print(f"Jarvis voice error: {exc}")
                self.assistant.state.set(AssistantStatus.ERROR)
            except asyncio.CancelledError:
                self.assistant.state.set(self._idle_status)
                raise
            finally:
                if not speech_owns_cleanup:
                    await self._call_hook(self.after_activation)

    async def _speak(self, text: str, language: str) -> None:
        self.assistant.state.set(AssistantStatus.SPEAKING)
        try:
            await self._call_hook(self.during_speech)
            await self.speaker.speak(text, language)
        except SpeechInterruptedError:
            pass
        except PiperError as exc:
            self.log.error("Local speech output failed: %s", exc)
            print(f"Jarvis speech error: {exc}")
        finally:
            barge_in = bool(
                self._activation_task
                and not self._activation_task.done()
                and self._activation_task.get_name() == "jarvis-voice-barge-in"
            )
            await self._call_hook(self.before_activation)
            if self.assistant.state.status is AssistantStatus.SPEAKING:
                self.assistant.state.set(self._idle_status)
            if not barge_in:
                await self._call_hook(self.after_activation)

    async def close(self) -> None:
        self._record_cancel.set()
        if self.hotkeys:
            self.hotkeys.stop()
            self.hotkeys = None
        task = self._activation_task
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await self.stop_speaking()
        await self.speaker.close()
        self.assistant.state.set(self._idle_status)
