"""
Event models that flow through the bus and out over the WebSocket.

Every event has a `type` string (dot-namespaced, e.g. "audio.onset") and a
`ts` timestamp so downstream consumers (Stage 2 classifier, Stage 3
renderer) can reason about ordering and latency without guessing.
"""
from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import BaseModel, Field


def _now() -> float:
    return time.time()


class BaseEvent(BaseModel):
    ts: float = Field(default_factory=_now)

    def to_wire(self) -> dict[str, Any]:
        """Dict shape sent over the WebSocket, always includes `type`."""
        data = self.model_dump()
        data["type"] = self.type  # type: ignore[attr-defined]
        return data


class LibraryReadyEvent(BaseEvent):
    type: Literal["rekordbox.library.ready"] = "rekordbox.library.ready"
    track_count: int
    source: Literal["db", "xml"]


class NowPlayingEvent(BaseEvent):
    type: Literal["rekordbox.now_playing"] = "rekordbox.now_playing"
    track_id: str | None = None
    title: str | None = None
    artist: str | None = None
    bpm: float | None = None
    key: str | None = None
    confidence: Literal["confirmed", "guessed"] = "guessed"


class AudioOnsetEvent(BaseEvent):
    type: Literal["audio.onset"] = "audio.onset"
    strength: float  # relative onset strength, not normalized to a fixed scale yet


class AudioTempoEvent(BaseEvent):
    type: Literal["audio.tempo"] = "audio.tempo"
    bpm: float
    confidence: float  # 0..1, from aubio's tempo tracker (or fallback estimate)


class AudioLevelEvent(BaseEvent):
    type: Literal["audio.level"] = "audio.level"
    rms: float
    peak: float


class ErrorEvent(BaseEvent):
    type: Literal["system.error"] = "system.error"
    source: str
    message: str
