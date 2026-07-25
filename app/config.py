"""
Central settings, loaded from environment variables / a .env file.

Keeping this as one small module (rather than scattering os.environ calls
everywhere) means Stage 2/3 can add their own settings here without hunting
through the codebase.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # --- Audio capture ---
    # Name (or substring) of the input device to capture from. On macOS this
    # should be your BlackHole device; on Windows, your normal output device
    # name (loopback is requested automatically). Run
    # scripts/list_audio_devices.py to find the exact string.
    audio_device_name: str = ""

    # Sample rate + block size for the live analysis loop. 44100/512 is a
    # reasonable default: ~11.6ms per block, low enough latency for onset
    # detection without pegging a CPU core.
    audio_sample_rate: int = 44100
    audio_block_size: int = 512

    # --- Rekordbox ---
    # Leave blank to let pyrekordbox auto-detect the install + db location.
    rekordbox_db_dir: str = ""

    # How often (seconds) the now-playing poller checks the database.
    # This is a coarse poll, NOT the real-time signal — the audio pipeline
    # is what gives you low-latency "something changed" detection. This
    # poller is for confirming *which* library track is playing.
    rekordbox_poll_interval_seconds: float = 1.5

    # --- Server ---
    log_level: str = "INFO"


settings = Settings()
