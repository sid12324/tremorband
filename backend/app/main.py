"""TremorBand API entrypoint.

TremorBand is a monitoring aid, not a diagnostic device.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.db import init_db
from app.live import live_hub
from app.routes import devices, ingest, live

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

DISCLAIMER = "TremorBand is a monitoring aid, not a diagnostic device."


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Create tables and bind the live broadcaster to this process."""
    init_db()
    live_hub.bind(asyncio.get_running_loop())
    logger.info("TremorBand API ready. %s", DISCLAIMER)
    yield


app = FastAPI(
    title="TremorBand",
    version=__version__,
    description=DISCLAIMER,
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(ingest.router)
app.include_router(devices.router)
app.include_router(live.router)


@app.get("/api/health")
def health() -> dict[str, str]:
    """Liveness check used by the simulator."""
    return {"status": "ok", "service": "tremorband"}


@app.get("/")
def root() -> dict[str, str]:
    """Point a browser at the Live page and restate the disclaimer."""
    return {
        "service": "tremorband",
        "disclaimer": DISCLAIMER,
        "live_page": "http://127.0.0.1:5173",
        "docs": "/docs",
    }
