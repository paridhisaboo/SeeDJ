"""
Live "what's currently playing in Rekordbox" poller.

Grounded in your actual database schema (not guessed) — confirmed via
`scripts/explore_rekordbox_schema.py` against a real Rekordbox 7 / macOS
install:

    djmdSongHistory: ContentID, HistoryID, TrackNo, created_at, updated_at
    djmdHistory:     Name, DateCreated, Seq  (one row per History playlist/session)

Rekordbox's "History" feature auto-logs played tracks as you DJ — each
track that plays gets a `DjmdSongHistory` row pointing at its `DjmdContent`
via `ContentID`. The most-recently-created row across ALL history sessions
(not just the latest `HistoryID`) is, by definition, the most recently
played track — so we don't need to first find "the active session," just
order by `created_at` descending and take the top row.

Caveat worth knowing: this depends on Rekordbox's history-logging being
enabled, which it is by default, but if you ever find this poller isn't
picking up track changes, check Rekordbox's preferences for anything
related to "Auto Create History Playlist" / play history logging, and
confirm by playing a track then re-running explore_rekordbox_schema.py to
see whether a fresh djmdSongHistory row with a recent created_at appears.
"""
from __future__ import annotations

import asyncio
import logging

from app.bus import bus
from app.config import settings
from app.events import ErrorEvent, NowPlayingEvent
from app.rekordbox.library import RekordboxLibrary

logger = logging.getLogger(__name__)


class NowPlayingPoller:
    def __init__(self, library: RekordboxLibrary) -> None:
        self.library = library
        self._last_content_id: str | None = None

    async def run_forever(self) -> None:
        if self.library.source != "db":
            logger.warning(
                "now_playing polling requires DB mode (XML export is a static "
                "snapshot, not live) — skipping. Library opened via: %s",
                self.library.source,
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
        from pyrekordbox.db6.tables import DjmdSongHistory

        db = self.library._db  # noqa: SLF001 - this module and library.py are tightly coupled by design
        if db is None or db.session is None:
            return

        latest = (
            db.session.query(DjmdSongHistory)
            .order_by(DjmdSongHistory.created_at.desc())
            .first()
        )
        if latest is None or not latest.ContentID:
            return

        if latest.ContentID == self._last_content_id:
            return  # no change since last poll

        self._last_content_id = latest.ContentID

        track = self.library.get_track_by_id(latest.ContentID)
        if track is None:
            logger.warning(
                "djmdSongHistory pointed at ContentID=%s but no matching "
                "DjmdContent found (deleted track?)",
                latest.ContentID,
            )
            return

        await bus.publish(
            NowPlayingEvent(
                track_id=track.id,
                title=track.title,
                artist=track.artist,
                bpm=track.bpm,
                key=track.key,
                confidence="confirmed",
            ).to_wire()
        )
        logger.info("Now playing: %s — %s", track.title, track.artist)