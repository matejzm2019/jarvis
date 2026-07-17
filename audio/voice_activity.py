"""Adaptive local energy-based voice activity detection."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class VoiceFrame:
    """VAD decision and measurements for one mono audio block."""

    speech: bool
    rms: float
    threshold: float


class VoiceActivityDetector:
    """Detect speech with a short noise calibration and adaptive floor."""

    def __init__(
        self,
        base_threshold: float,
        warmup_frames: int = 10,
        noise_multiplier: float = 2.5,
        adaptation_rate: float = 0.08,
    ) -> None:
        if not 0 <= base_threshold <= 1:
            raise ValueError("base_threshold must be between 0 and 1")
        self.base_threshold = base_threshold
        self.warmup_frames = max(0, warmup_frames)
        self.noise_multiplier = max(1, noise_multiplier)
        self.adaptation_rate = min(1, max(0, adaptation_rate))
        self.reset()

    def reset(self) -> None:
        """Discard prior noise calibration for a new activation."""
        self._frames = 0
        self._noise_floor = max(1e-5, self.base_threshold / self.noise_multiplier)

    def analyze(self, samples: np.ndarray) -> VoiceFrame:
        """Classify normalized float audio without retaining it."""
        mono = np.asarray(samples, dtype=np.float32).reshape(-1)
        rms = float(np.sqrt(np.mean(np.square(mono, dtype=np.float32)))) if mono.size else 0.0
        if self._frames < self.warmup_frames:
            self._frames += 1
            threshold = max(self.base_threshold, self._noise_floor * self.noise_multiplier)
            speech = rms >= threshold * 1.5
            if not speech:
                rate = 1 / self._frames
                self._noise_floor += (rms - self._noise_floor) * rate
            return VoiceFrame(speech, rms, threshold)

        threshold = max(self.base_threshold, self._noise_floor * self.noise_multiplier)
        speech = rms >= threshold
        if not speech:
            self._noise_floor += (rms - self._noise_floor) * self.adaptation_rate
        self._frames += 1
        return VoiceFrame(speech, rms, threshold)
