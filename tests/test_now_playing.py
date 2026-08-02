"""
Tests NowPlayingPoller's polling logic without needing a real Rekordbox
database — mocks db.session.query(...).order_by(...).first() to return
fake DjmdSongHistory-shaped rows, and RekordboxLibrary.get_track_by_id to
return fake Track objects. This tests OUR change-detection/event-emission
logic, not pyrekordbox's ORM (which is pyrekordbox's own tested concern).
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.bus import bus
from app.rekordbox.library import Track
from app.rekordbox.now_playing import NowPlayingPoller


def _make_fake_song_history_row(content_id: str):
    return SimpleNamespace(ContentID=content_id)


def _make_mock_library(source="db"):
    lib = MagicMock()
    lib.source = source
    return lib


def _wire_query_chain(lib, row):
    """Wires lib._db.session.query(...).order_by(...).first() -> row."""
    query_mock = MagicMock()
    query_mock.order_by.return_value.first.return_value = row
    lib._db.session.query.return_value = query_mock
    return query_mock


@pytest.mark.asyncio
async def test_poll_once_publishes_event_on_new_track(monkeypatch):
    lib = _make_mock_library()
    row = _make_fake_song_history_row("track-123")
    _wire_query_chain(lib, row)
    lib.get_track_by_id.return_value = Track(
        id="track-123", title="Test Track", artist="Test Artist", bpm=128.0,
        key="8A", length_seconds=300.0, analysis_data_path=None, source="db",
    )

    # Patch the pyrekordbox import inside _poll_once so this test doesn't
    # require pyrekordbox to be installed.
    import sys
    fake_module = SimpleNamespace(DjmdSongHistory=MagicMock())
    monkeypatch.setitem(sys.modules, "pyrekordbox.db6.tables", fake_module)

    poller = NowPlayingPoller(lib)
    events = []
    queue = bus.subscribe()

    await poller._poll_once()

    event = queue.get_nowait()
    assert event["type"] == "rekordbox.now_playing"
    assert event["title"] == "Test Track"
    assert event["confidence"] == "confirmed"
    bus.unsubscribe(queue)


@pytest.mark.asyncio
async def test_poll_once_does_not_republish_same_track(monkeypatch):
    lib = _make_mock_library()
    row = _make_fake_song_history_row("track-123")
    _wire_query_chain(lib, row)
    lib.get_track_by_id.return_value = Track(
        id="track-123", title="Test Track", artist="Test Artist", bpm=128.0,
        key="8A", length_seconds=300.0, analysis_data_path=None, source="db",
    )

    import sys
    fake_module = SimpleNamespace(DjmdSongHistory=MagicMock())
    monkeypatch.setitem(sys.modules, "pyrekordbox.db6.tables", fake_module)

    poller = NowPlayingPoller(lib)
    queue = bus.subscribe()

    await poller._poll_once()
    queue.get_nowait()  # first event, expected

    await poller._poll_once()  # same ContentID again
    assert queue.empty(), "Should not publish a duplicate event for the same track"
    bus.unsubscribe(queue)


@pytest.mark.asyncio
async def test_poll_once_handles_empty_history_gracefully(monkeypatch):
    lib = _make_mock_library()
    _wire_query_chain(lib, None)  # no history rows at all

    import sys
    fake_module = SimpleNamespace(DjmdSongHistory=MagicMock())
    monkeypatch.setitem(sys.modules, "pyrekordbox.db6.tables", fake_module)

    poller = NowPlayingPoller(lib)
    queue = bus.subscribe()

    await poller._poll_once()  # should not raise

    assert queue.empty()
    bus.unsubscribe(queue)


def test_run_forever_skips_cleanly_when_library_is_xml_mode():
    lib = _make_mock_library(source="xml")
    poller = NowPlayingPoller(lib)

    # run_forever should return immediately (not hang/loop) for XML mode —
    # verify by running it with a timeout.
    async def _run():
        await asyncio.wait_for(poller.run_forever(), timeout=1.0)

    asyncio.run(_run())