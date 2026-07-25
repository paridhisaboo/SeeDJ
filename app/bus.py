"""
Minimal async pub/sub. Deliberately not a message queue library — Stage 1
has exactly one producer-consumer shape (background tasks -> WebSocket
clients) and doesn't need Redis/etc yet. If Stage 2/3 need cross-process
delivery (e.g. classifier as a separate service), swap this for something
like Redis pub/sub or a proper queue then; don't build for that now.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    async def publish(self, event: dict[str, Any]) -> None:
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Slow consumer — drop the event rather than block the
                # producer (audio loop) or grow memory unbounded.
                logger.warning("Subscriber queue full, dropping event: %s", event.get("type"))


bus = EventBus()
