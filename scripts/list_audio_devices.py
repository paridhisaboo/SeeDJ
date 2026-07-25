"""
Run this to find the device name to put in AUDIO_DEVICE_NAME (.env).

macOS: look for "BlackHole 2ch" (after installing it — see README).
Windows: look for your actual output device (e.g. "Speakers (Realtek...)")
  — loopback is requested automatically, you don't need a separate entry.
Linux: look for a "Monitor of ..." source.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.audio.capture import list_devices  # noqa: E402


def main() -> None:
    print("Available input/loopback-capable devices:\n")
    for name in list_devices():
        print(f"  {name}")
    print(
        "\nCopy the relevant one (or a distinctive substring of it) into "
        "AUDIO_DEVICE_NAME in your .env file."
    )


if __name__ == "__main__":
    main()
