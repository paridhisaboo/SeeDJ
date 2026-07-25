"""
Cross-platform audio capture.

Uses `soundcard`, which supports native WASAPI loopback recording on
Windows (no virtual cable needed) and treats any input device — including
a virtual one like BlackHole on macOS, or a PulseAudio monitor source on
Linux — as a normal microphone. See README for the one-time OS-specific
setup (BlackHole + Multi-Output Device on macOS; nothing extra on Windows).

`soundcard`'s recording call is blocking, so we run it in a thread and
bridge to asyncio with a queue, rather than blocking the event loop.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import AsyncIterator

import numpy as np

logger = logging.getLogger(__name__)


def list_devices() -> list[str]:
    import soundcard as sc

    names: list[str] = []
    try:
        for mic in sc.all_microphones(include_loopback=True):
            names.append(f"{mic.name}  [loopback-capable input]")
    except TypeError:
        # Older soundcard versions on some platforms don't accept
        # include_loopback for all_microphones(); fall back gracefully.
        for mic in sc.all_microphones():
            names.append(mic.name)
    return names


def _resolve_microphone(device_name_substring: str):  # noqa: ANN201
    import soundcard as sc

    candidates = sc.all_microphones(include_loopback=True)
    if not device_name_substring:
        raise ValueError(
            "AUDIO_DEVICE_NAME is not set. Run scripts/list_audio_devices.py "
            "and put a matching device name in your .env file."
        )

    matches = [m for m in candidates if device_name_substring.lower() in m.name.lower()]
    if not matches:
        available = "\n".join(f"  - {m.name}" for m in candidates)
        raise ValueError(
            f"No audio device matching '{device_name_substring}'. Available devices:\n{available}"
        )
    if len(matches) > 1:
        logger.warning(
            "Multiple devices matched '%s', using the first: %s",
            device_name_substring,
            matches[0].name,
        )
    return matches[0]


class AudioCapture:
    """
    Async iterator over raw audio blocks (mono float32 numpy arrays).

    Usage:
        capture = AudioCapture(device_name, sample_rate, block_size)
        async for block in capture.blocks():
            ...
    """

    def __init__(self, device_name: str, sample_rate: int, block_size: int) -> None:
        self.device_name = device_name
        self.sample_rate = sample_rate
        self.block_size = block_size
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    async def blocks(self) -> AsyncIterator[np.ndarray]:
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue[np.ndarray | None] = asyncio.Queue(maxsize=32)

        def _record_thread() -> None:
            import soundcard as sc  # imported in-thread: soundcard opens platform audio APIs lazily

            try:
                mic = _resolve_microphone(self.device_name)
            except Exception as exc:  # noqa: BLE001
                logger.error("Audio capture failed to start: %s", exc)
                asyncio.run_coroutine_threadsafe(queue.put(None), loop)
                return

            logger.info("Recording from: %s", mic.name)
            try:
                with mic.recorder(samplerate=self.sample_rate, channels=1) as recorder:
                    while not self._stop_event.is_set():
                        data = recorder.record(numframes=self.block_size)
                        # soundcard returns shape (frames, channels); flatten to mono.
                        mono = data.reshape(-1).astype(np.float32)
                        asyncio.run_coroutine_threadsafe(queue.put(mono), loop)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Audio recording thread crashed")
                asyncio.run_coroutine_threadsafe(queue.put(None), loop)

        thread = threading.Thread(target=_record_thread, daemon=True)
        thread.start()

        try:
            while True:
                block = await queue.get()
                if block is None:
                    logger.warning("Audio capture stream ended.")
                    return
                yield block
        finally:
            self.stop()
