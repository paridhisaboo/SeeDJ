"""
Best-effort "what's currently playing in Rekordbox" poller.

READ THIS BEFORE TRUSTING THIS MODULE'S OUTPUT:

Rekordbox does not expose an official, documented "now playing" signal for
laptop-only software mode (that's the Pro DJ Link hardware world, which
needs real CDJs on a network — see the research brief). The best available
proxy is polling the local database for the most recently touched
history/play-related row, but:

  - The exact table (`DjmdSongHistory`, `DjmdHistory`, something else
    depending on version) and the column that reflects "most recent" vs.
    "most recently added to a saved history playlist" (which is NOT the
    same thing as "currently playing") are not confirmed here.
  - This has NOT been verified against a live install. Run
    `scripts/explore_rekordbox_schema.py` while a track is playing, diff
    the output before/after switching tracks, and find the table/column
    that actually changes in real time. Then fill in the constants below.

Until you've done that verification, `poll_once()` will raise
NotImplementedError with a pointer back to this docstring — better to fail
loudly than silently return wrong track info to the classifier downstream.

Once verified, the intended shape is: poll every
`settings.rekordbox_poll_interval_seconds`, diff against the last seen row,
and emit a NowPlayingEvent with confidence="confirmed" when the DB row
matches, or confidence="guessed" if you're inferring from BPM/audio
matching instead (see app/audio/features.py for the tempo signal you'd
cross-reference against RekordboxLibrary.find_by_bpm_range()).
"""
from __future__ import annotations

import asyncio
import logging

from app.bus import bus
from app.config import settings
from app.events import ErrorEvent, NowPlayingEvent
from app.rekordbox.library import RekordboxLibrary

logger = logging.getLogger(__name__)

# --- Fill these in after running scripts/explore_rekordbox_schema.py ---
HISTORY_TABLE_NAME: str | None = None  # e.g. "DjmdSongHistory"
HISTORY_TIMESTAMP_COLUMN: str | None = None  # e.g. "updated_at" / "created_at"
HISTORY_CONTENT_ID_COLUMN: str | None = None  # e.g. "ContentID"
# -------------------------------------------------------------------


class NowPlayingPoller:
    def __init__(self, library: RekordboxLibrary) -> None:
        self.library = library
        self._last_track_id: str | None = None
        self._verified = all(
            [HISTORY_TABLE_NAME, HISTORY_TIMESTAMP_COLUMN, HISTORY_CONTENT_ID_COLUMN]
        )

    async def run_forever(self) -> None:
        if not self._verified:
            logger.warning(
                "now_playing schema not verified yet — skipping live polling. "
                "See app/rekordbox/now_playing.py docstring for how to fix this. "
                "The rest of the pipeline (library + live audio) works fine without it."
            )
            await bus.publish(
                ErrorEvent(
                    source="rekordbox.now_playing",
                    message=(
                        "Now-playing schema unverified for your Rekordbox version. "
                        "Run scripts/explore_rekordbox_schema.py to fix — see README."
                    ),
                ).to_wire()
            )
            return

        while True:
            try:
                await self._poll_once()
            except Exception as exc:  # noqa: BLE001 - keep the loop alive
                logger.exception("now_playing poll failed")
                await bus.publish(
                    ErrorEvent(source="rekordbox.now_playing", message=str(exc)).to_wire()
                )
            await asyncio.sleep(settings.rekordbox_poll_interval_seconds)

    async def _poll_once(self) -> None:
        # Implemented once HISTORY_TABLE_NAME etc. are verified. Sketch:
        #
        #   from sqlalchemy import text
        #   row = self.library._db.session.execute(
        #       text(f"SELECT {HISTORY_CONTENT_ID_COLUMN} FROM {HISTORY_TABLE_NAME} "
        #            f"ORDER BY {HISTORY_TIMESTAMP_COLUMN} DESC LIMIT 1")
        #   ).first()
        #   ... look up the track in self.library, compare to self._last_track_id,
        #   ... publish a NowPlayingEvent if it changed.
        #
        # Left unimplemented until verified against a real install rather
        # than guessing the query and shipping something that looks like it
        # works but returns stale/wrong data.
        raise NotImplementedError
