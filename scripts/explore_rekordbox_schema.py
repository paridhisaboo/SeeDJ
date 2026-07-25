"""
Dumps every table and column name in your local Rekordbox database.

How to use this to fix app/rekordbox/now_playing.py:
  1. Run this script once, save the output (or just note table names
     containing "History" or "PlayerSetting" or similar).
  2. Play a track in Rekordbox.
  3. Run this script again.
  4. Diff the two runs — for tables that are polling-friendly, you're
     looking for one where a row's timestamp column changed to "now".
  5. Put the table name + timestamp column + content-id column into the
     constants at the top of app/rekordbox/now_playing.py.

This is intentionally a manual, one-time investigation rather than
something the app does automatically — Rekordbox's schema isn't public API,
so a human sanity-check before wiring it into a poller that feeds a
classifier is worth the five minutes.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.rekordbox.library import explore_schema  # noqa: E402


def main() -> None:
    report = explore_schema()
    print(json.dumps(report, indent=2))
    print(f"\n{len(report)} tables found.", file=sys.stderr)
    print(
        "Look for table names containing 'History', 'Song', or 'Player' — "
        "those are your best candidates for a now-playing signal.",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
