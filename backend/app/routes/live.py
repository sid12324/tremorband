"""Server-sent events for the Live page."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.live import live_hub

router = APIRouter(prefix="/api", tags=["live"])


async def _event_stream() -> AsyncIterator[str]:
    queue = live_hub.subscribe()
    try:
        yield "event: hello\ndata: {\"ok\": true}\n\n"
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=15)
            except TimeoutError:
                yield ": keepalive\n\n"
                continue
            payload = json.dumps(event["data"], separators=(",", ":"))
            yield f"event: {event['type']}\ndata: {payload}\n\n"
    finally:
        live_hub.unsubscribe(queue)


@router.get("/live")
async def live() -> StreamingResponse:
    """Push windows, device status, and command updates."""
    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
