"""
Bridges the internal event bus to WebSocket clients. Each client gets its
own subscription queue so a slow client can't block others (the bus already
drops events on a full queue rather than backpressuring the producer — see
bus.py).
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import WebSocket, WebSocketDisconnect

from app.bus import bus

logger = logging.getLogger(__name__)


async def handle_client(websocket: WebSocket) -> None:
    await websocket.accept()
    queue = bus.subscribe()
    logger.info("WebSocket client connected")

    try:
        while True:
            event = await queue.get()
            await websocket.send_json(event)
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception:  # noqa: BLE001
        logger.exception("WebSocket client loop crashed")
    finally:
        bus.unsubscribe(queue)
