"""On-demand microphone recording with adaptive silence stop."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from collections import deque
from dataclasses import dataclass
from typing import Any

import numpy as np

from audio.voice_activity import VoiceActivityDetector
from config import AudioConfig, SpeechToTextConfig


class AudioError(RuntimeError):
    """Local audio-device or recording failure."""


class NoSpeechDetected(AudioError):
    pass


@dataclass(frozen=True, slots=True)
class AudioRecording:
    """Transient normalized mono audio held only in memory."""

    samples: np.ndarray
    sample_rate: int

    @property
    def duration_seconds(self) -> float:
        return len(self.samples) / self.sample_rate


class AudioRecorder:
    """Record only after activation; never persist raw microphone audio."""

    def __init__(self, audio: AudioConfig, speech: SpeechToTextConfig) -> None:
        self.audio = audio
        frames_per_second = 1000 / audio.block_duration_ms
        self.vad = VoiceActivityDetector(
            speech.silence_threshold,
            warmup_frames=max(1, round(frames_per_second * 0.25)),
        )
        self.log = logging.getLogger("jarvis.audio.recorder")

    @staticmethod
    def list_input_devices() -> list[dict[str, Any]]:
        """List PortAudio devices that expose input channels."""
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise AudioError("sounddevice is not installed") from exc
        devices = sd.query_devices()
        return [
            {
                "index": index,
                "name": str(device["name"]),
                "input_channels": int(device["max_input_channels"]),
                "default_sample_rate": int(device["default_samplerate"]),
            }
            for index, device in enumerate(devices)
            if int(device["max_input_channels"]) > 0
        ]

    async def record(self, cancel: asyncio.Event | None = None) -> AudioRecording:
        """Capture one utterance, stopping after configured post-speech silence."""
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise AudioError("sounddevice is not installed") from exc

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[np.ndarray] = asyncio.Queue()
        block_size = round(self.audio.sample_rate * self.audio.block_duration_ms / 1000)
        pre_roll_blocks = max(1, round(self.audio.pre_roll_seconds * 1000 / self.audio.block_duration_ms))
        pre_roll: deque[np.ndarray] = deque(maxlen=pre_roll_blocks)
        captured: list[np.ndarray] = []
        speech_started = False
        voiced_samples = 0
        silent_samples = 0
        maximum_samples = round(self.audio.maximum_recording_seconds * self.audio.sample_rate)
        silence_samples = round(self.audio.silence_timeout_seconds * self.audio.sample_rate)
        minimum_samples = round(self.audio.minimum_speech_seconds * self.audio.sample_rate)
        self.vad.reset()

        def callback(indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
            del frames, time_info
            if status:
                self.log.warning("PortAudio input status: %s", status)
            try:
                loop.call_soon_threadsafe(queue.put_nowait, np.asarray(indata[:, 0], dtype=np.float32).copy())
            except RuntimeError:
                return

        try:
            with sd.InputStream(
                samplerate=self.audio.sample_rate,
                blocksize=block_size,
                device=self.audio.microphone_device,
                channels=1,
                dtype="float32",
                callback=callback,
            ):
                total_samples = 0
                deadline = loop.time() + self.audio.maximum_recording_seconds
                while total_samples < maximum_samples and loop.time() < deadline:
                    if cancel and cancel.is_set():
                        raise asyncio.CancelledError
                    try:
                        block = await asyncio.wait_for(queue.get(), timeout=0.25)
                    except TimeoutError:
                        continue
                    total_samples += len(block)
                    decision = self.vad.analyze(block)
                    if not speech_started:
                        pre_roll.append(block)
                        if decision.speech:
                            speech_started = True
                            captured.extend(pre_roll)
                            voiced_samples += len(block)
                            pre_roll.clear()
                        continue
                    captured.append(block)
                    if decision.speech:
                        voiced_samples += len(block)
                        silent_samples = 0
                    else:
                        silent_samples += len(block)
                        if silent_samples >= silence_samples:
                            break
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise AudioError(f"Microphone recording failed: {exc}") from exc

        if not speech_started or voiced_samples < minimum_samples or not captured:
            raise NoSpeechDetected("No clear speech was detected")
        samples = np.concatenate(captured).astype(np.float32, copy=False)
        return AudioRecording(samples=samples, sample_rate=self.audio.sample_rate)


def main() -> None:
    parser = argparse.ArgumentParser(description="List local microphone input devices")
    parser.parse_args()
    print(json.dumps(AudioRecorder.list_input_devices(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
