"""In-process broadcaster for the Live page event stream."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class LiveHub:
    """Fan out JSON events to server-sent-event subscribers.

    Ingest handlers run in worker threads, so ``publish`` hops back onto the
    application event loop.
    """

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._latest_windows: dict[str, dict[str, Any]] = {}

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        """Remember the loop that owns the subscriber queues."""
        self._loop = loop

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        """Register a subscriber queue."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=200)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """Drop a subscriber queue."""
        self._subscribers.discard(queue)

    def latest_window(self, device_id: str) -> dict[str, Any] | None:
        """Return the newest broadcast window for a device, if any."""
        latest = self._latest_windows.get(device_id)
        if latest is None:
            return None
        return dict(latest)

    def publish(self, event_type: str, data: dict[str, Any]) -> None:
        """Queue an event for every current subscriber."""
        if event_type == "window":
            device_id = str(data.get("device_id", ""))
            if device_id:
                self._latest_windows[device_id] = dict(data)
        loop = self._loop
        if loop is None or loop.is_closed():
            logger.debug("dropping %s event; live loop is not ready", event_type)
            return
        event = {"type": event_type, "data": data}
        for queue in list(self._subscribers):
            loop.call_soon_threadsafe(self._offer, queue, event)

    def _offer(self, queue: asyncio.Queue[dict[str, Any]], event: dict[str, Any]) -> None:
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                return
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.debug("dropping event for a full subscriber")


live_hub = LiveHub()
