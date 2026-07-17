import numpy as np

from audio.voice_activity import VoiceActivityDetector


def test_detects_speech_after_quiet_calibration() -> None:
    detector = VoiceActivityDetector(0.01, warmup_frames=2)
    assert not detector.analyze(np.zeros(480, dtype=np.float32)).speech
    assert not detector.analyze(np.full(480, 0.002, dtype=np.float32)).speech
    result = detector.analyze(np.full(480, 0.08, dtype=np.float32))
    assert result.speech
    assert result.rms > result.threshold


def test_empty_and_quiet_frames_are_not_speech() -> None:
    detector = VoiceActivityDetector(0.01, warmup_frames=0)
    assert not detector.analyze(np.array([], dtype=np.float32)).speech
    assert not detector.analyze(np.full(160, 0.001, dtype=np.float32)).speech

