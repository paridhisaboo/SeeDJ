from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket

from app.audio.capture import AudioCapture
from app.audio.features import RealtimeFeatureExtractor
from app.bus import bus
from app.config import settings
from app.events import ErrorEvent, LibraryReadyEvent
from app.rekordbox.library import RekordboxLibrary
from app.rekordbox.now_playing import NowPlayingPoller
from app.ws.manager import handle_client

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)

_background_tasks: set[asyncio.Task] = set()


async def _run_rekordbox_library() -> RekordboxLibrary | None:
    try:
        library = RekordboxLibrary(db_dir=settings.rekordbox_db_dir or None)
    except Exception as exc:  # noqa: BLE001
        logger.error("Rekordbox library failed to open: %s", exc)
        await bus.publish(ErrorEvent(source="rekordbox.library", message=str(exc)).to_wire())
        return None

    count = library.count()
    logger.info("Rekordbox library ready: %d tracks (%s)", count, library.source)
    await bus.publish(
        LibraryReadyEvent(track_count=count, source=library.source).to_wire()  # type: ignore[arg-type]
    )
    return library


async def _run_audio_pipeline() -> None:
    if not settings.audio_device_name:
        logger.warning(
            "AUDIO_DEVICE_NAME not set — live audio pipeline disabled. "
            "Run scripts/list_audio_devices.py and set it in .env to enable."
        )
        await bus.publish(
            ErrorEvent(
                source="audio",
                message="AUDIO_DEVICE_NAME not set; live audio pipeline disabled.",
            ).to_wire()
        )
        return

    capture = AudioCapture(
        device_name=settings.audio_device_name,
        sample_rate=settings.audio_sample_rate,
        block_size=settings.audio_block_size,
    )
    extractor = RealtimeFeatureExtractor(
        sample_rate=settings.audio_sample_rate, block_size=settings.audio_block_size
    )
    logger.info("Audio pipeline started (backend=%s)", extractor.backend)

    async for block in capture.blocks():
        for event in extractor.process_block(block):
            await bus.publish(event.to_wire())


@asynccontextmanager
async def lifespan(app: FastAPI):
    library = await _run_rekordbox_library()

    if library is not None:
        poller = NowPlayingPoller(library)
        task = asyncio.create_task(poller.run_forever())
        _background_tasks.add(task)

    audio_task = asyncio.create_task(_run_audio_pipeline())
    _background_tasks.add(audio_task)

    yield

    for task in _background_tasks:
        task.cancel()
    await asyncio.gather(*_background_tasks, return_exceptions=True)


app = FastAPI(title="DJ Visualizer — Stage 1", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.websocket("/ws/events")
async def ws_events(websocket: WebSocket) -> None:
    await handle_client(websocket)
