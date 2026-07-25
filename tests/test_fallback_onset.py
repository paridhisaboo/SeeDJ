"""
These test the fallback DSP logic in isolation, since it's the only part
of Stage 1 that doesn't depend on real hardware (an actual audio loopback
device or an actual Rekordbox install). The aubio path, capture.py, and
the Rekordbox adapters need to be smoke-tested manually against real
setups (see scripts/) rather than unit tested here.
"""
import numpy as np

from app.audio.fallback_onset import FallbackOnsetDetector, FallbackTempoEstimator


def test_onset_detector_flags_a_sudden_transient():
    block_size = 512
    sample_rate = 44100
    detector = FallbackOnsetDetector(block_size=block_size)

    silence = np.zeros(block_size, dtype=np.float32)
    t = np.arange(block_size) / sample_rate
    loud_tone = (0.9 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)

    # Feed a few silent blocks to establish a low baseline flux history,
    # then a sudden loud block — that transition should register as an onset.
    onsets = []
    for _ in range(5):
        _, is_onset = detector.process(silence)
        onsets.append(is_onset)

    _, is_onset = detector.process(loud_tone)
    onsets.append(is_onset)

    assert not any(onsets[:5]), "Silence should not trigger onsets"
    assert onsets[5], "A sudden loud transient after silence should trigger an onset"


def test_tempo_estimator_recovers_known_bpm():
    estimator = FallbackTempoEstimator()
    target_bpm = 128.0
    interval = 60.0 / target_bpm

    t = 0.0
    for _ in range(16):
        estimator.register_onset(when=t)
        t += interval

    bpm, confidence = estimator.estimate()

    assert bpm is not None
    assert abs(bpm - target_bpm) <= 2.0, f"Expected ~{target_bpm} BPM, got {bpm}"
    assert confidence > 0.5


def test_tempo_estimator_returns_none_with_insufficient_data():
    estimator = FallbackTempoEstimator()
    estimator.register_onset(when=0.0)
    estimator.register_onset(when=0.5)

    bpm, confidence = estimator.estimate()

    assert bpm is None
    assert confidence == 0.0
