"""
Pure-numpy fallback for onset/tempo detection, used only if `aubio` isn't
installed. This exists so the pipeline still runs (degraded) rather than
hard-failing on an environment where aubio's C build didn't work — see
README for how to fix aubio properly; this is a stopgap, not a replacement.

Deliberately simple:
  - Onset detection: spectral flux (sum of positive magnitude-spectrum
    differences between consecutive frames) with an adaptive threshold
    (moving average + margin). This is a well-known, if basic, onset
    detection function — nowhere near aubio's accuracy but good enough to
    keep the event stream flowing.
  - Tempo estimation: inter-onset-interval histogram over a rolling window,
    binned into plausible BPM range. Confidence is just "fraction of
    recent intervals landing in the winning bin" — a rough proxy, not a
    calibrated probability.
"""
from __future__ import annotations

import time
from collections import deque

import numpy as np


class FallbackOnsetDetector:
    def __init__(self, block_size: int, history: int = 10, threshold_margin: float = 1.5) -> None:
        self.block_size = block_size
        self._prev_spectrum: np.ndarray | None = None
        self._flux_history: deque[float] = deque(maxlen=history)
        self._threshold_margin = threshold_margin
        self._window = np.hanning(block_size)

    def process(self, block: np.ndarray) -> tuple[float, bool]:
        """Returns (onset_strength, is_onset) for this block."""
        if len(block) != self.block_size:
            # Last block from a stream can be short; pad rather than crash.
            block = np.pad(block, (0, self.block_size - len(block)))

        spectrum = np.abs(np.fft.rfft(block * self._window))

        if self._prev_spectrum is None:
            self._prev_spectrum = spectrum
            return 0.0, False

        flux = float(np.sum(np.maximum(spectrum - self._prev_spectrum, 0.0)))
        self._prev_spectrum = spectrum

        avg = float(np.mean(self._flux_history)) if self._flux_history else 0.0
        is_onset = flux > avg * self._threshold_margin and flux > 0.0
        self._flux_history.append(flux)

        return flux, is_onset


class FallbackTempoEstimator:
    def __init__(self, window_seconds: float = 8.0, min_bpm: float = 60.0, max_bpm: float = 200.0) -> None:
        self.window_seconds = window_seconds
        self.min_bpm = min_bpm
        self.max_bpm = max_bpm
        self._onset_times: deque[float] = deque()

    def register_onset(self, when: float | None = None) -> None:
        when = when if when is not None else time.time()
        self._onset_times.append(when)
        cutoff = when - self.window_seconds
        while self._onset_times and self._onset_times[0] < cutoff:
            self._onset_times.popleft()

    def estimate(self) -> tuple[float | None, float]:
        """Returns (bpm, confidence). bpm is None if not enough data yet."""
        times = list(self._onset_times)
        if len(times) < 4:
            return None, 0.0

        intervals = [t2 - t1 for t1, t2 in zip(times, times[1:]) if t2 > t1]
        if not intervals:
            return None, 0.0

        bpms = [60.0 / iv for iv in intervals if iv > 0]
        # Fold multiples/fractions into the target range (e.g. a detected
        # half-time or double-time interval still votes for the true tempo).
        folded = []
        for bpm in bpms:
            while bpm < self.min_bpm:
                bpm *= 2
            while bpm > self.max_bpm:
                bpm /= 2
            folded.append(bpm)

        if not folded:
            return None, 0.0

        # 2-BPM-wide histogram bins
        bins = np.round(np.array(folded) / 2.0) * 2.0
        values, counts = np.unique(bins, return_counts=True)
        winner_idx = int(np.argmax(counts))
        bpm = float(values[winner_idx])
        confidence = float(counts[winner_idx]) / len(folded)

        return bpm, confidence
