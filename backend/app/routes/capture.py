"""On/off capture control for the Session page."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, col, select

from app.capture import measurements, open_capture, start_capture, stop_capture
from app.db import get_session
from app.models import CaptureSession
from app.schemas import as_utc

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["capture"])


class CaptureIn(BaseModel):
    """Desired capture switch position."""

    on: bool


class CaptureSessionRead(BaseModel):
    """One capture session for the Session page."""

    id: int
    device_id: str
    ts_start: str
    ts_end: str | None
    n_windows: int
    is_synthetic: bool
    on: bool


class CaptureRead(BaseModel):
    """Whether capture is on, and the sessions the switch has created."""

    on: bool
    session_id: int | None
    sessions: list[CaptureSessionRead]


def _read(session: Session, row: CaptureSession) -> CaptureSessionRead:
    stats = measurements(session, row)
    started = as_utc(row.ts_start)
    ended = as_utc(row.ts_end)
    return CaptureSessionRead(
        id=row.id or 0,
        device_id=row.device_id,
        ts_start=started.isoformat() if started else "",
        ts_end=ended.isoformat() if ended else None,
        n_windows=int(stats["n_windows"] or 0),
        is_synthetic=row.is_synthetic,
        on=row.ts_end is None,
    )


def _view(session: Session) -> CaptureRead:
    current = open_capture(session)
    rows = list(
        session.exec(
            select(CaptureSession)
            .where(CaptureSession.test_type == "capture")
            .order_by(col(CaptureSession.id).desc())
        )
    )
    return CaptureRead(
        on=current is not None,
        session_id=current.id if current is not None else None,
        sessions=[_read(session, row) for row in rows if row.id is not None],
    )


@router.get("/capture", response_model=CaptureRead)
def get_capture(session: Session = Depends(get_session)) -> CaptureRead:
    """The switch position and the capture sessions it has opened."""
    return _view(session)


@router.post("/capture", response_model=CaptureRead)
def set_capture(body: CaptureIn, session: Session = Depends(get_session)) -> CaptureRead:
    """Turn capture on or off.

    Each transition from off to on creates a new session. Turning it on while
    a session is already open keeps that session. Turning it off stores the
    session's window numbers and stops assigning new windows to it.
    """
    if body.on:
        row = start_capture(session)
        logger.info("capture on session=%s", row.id)
    else:
        row = stop_capture(session)
        logger.info("capture off session=%s", None if row is None else row.id)
    session.commit()
    return _view(session)
