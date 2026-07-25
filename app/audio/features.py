"""
Turns raw audio blocks into onset/tempo/level events. Prefers `aubio`
(proper, well-validated onset/tempo tracking); falls back to
`fallback_onset.py`'s numpy implementation if aubio isn't installed, with a
clearly logged warning so you know which one you're running on.
"""
from __future__ import annotations

import logging
import time

import numpy as np

from app.audio.fallback_onset import FallbackOnsetDetector, FallbackTempoEstimator
from app.events import AudioLevelEvent, AudioOnsetEvent, AudioTempoEvent

logger = logging.getLogger(__name__)


class RealtimeFeatureExtractor:
    def __init__(self, sample_rate: int, block_size: int) -> None:
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.backend: str

        try:
            import aubio  # noqa: F401

            self.backend = "aubio"
            self._init_aubio()
        except ImportError:
            logger.warning(
                "aubio not installed — using the lower-accuracy numpy fallback "
                "onset/tempo detector. See README for how to install aubio properly."
            )
            self.backend = "fallback"
            self._onset_detector = FallbackOnsetDetector(block_size)
            self._tempo_estimator = FallbackTempoEstimator()

    def _init_aubio(self) -> None:
        import aubio

        # "default" method balances sensitivity/specificity reasonably;
        # aubio also offers "hfc", "complex", "specdiff", etc. if this
        # doesn't feel right for club music once you're testing against
        # real sets — worth an experiment in Stage 2.
        self._aubio_onset = aubio.onset("default", self.block_size * 2, self.block_size, self.sample_rate)
        self._aubio_tempo = aubio.tempo("default", self.block_size * 2, self.block_size, self.sample_rate)

    def process_block(self, block: np.ndarray) -> list:
        events: list = []
        now = time.time()

        # Level metering is backend-independent and cheap — always compute it.
        rms = float(np.sqrt(np.mean(np.square(block)))) if len(block) else 0.0
        peak = float(np.max(np.abs(block))) if len(block) else 0.0
        events.append(AudioLevelEvent(ts=now, rms=rms, peak=peak))

        if self.backend == "aubio":
            events.extend(self._process_aubio(block, now))
        else:
            events.extend(self._process_fallback(block, now))

        return events

    def _process_aubio(self, block: np.ndarray, now: float) -> list:
        import aubio

        events: list = []
        block32 = block.astype(np.float32)

        onset_result = self._aubio_onset(block32)
        if onset_result[0] > 0:
            # aubio's onset() returns a nonzero trigger sample; strength isn't
            # directly exposed by the simple call, so use the detection
            # function's last value as a proxy strength.
            strength = float(self._aubio_onset.get_descriptor())
            events.append(AudioOnsetEvent(ts=now, strength=strength))

        tempo_result = self._aubio_tempo(block32)
        if tempo_result[0] > 0:
            bpm = float(self._aubio_tempo.get_bpm())
            confidence = float(self._aubio_tempo.get_confidence())
            if bpm > 0:
                events.append(AudioTempoEvent(ts=now, bpm=bpm, confidence=confidence))

        return events

    def _process_fallback(self, block: np.ndarray, now: float) -> list:
        events: list = []

        strength, is_onset = self._onset_detector.process(block)
        if is_onset:
            events.append(AudioOnsetEvent(ts=now, strength=strength))
            self._tempo_estimator.register_onset(now)

        bpm, confidence = self._tempo_estimator.estimate()
        if bpm is not None:
            events.append(AudioTempoEvent(ts=now, bpm=bpm, confidence=confidence))

        return events
