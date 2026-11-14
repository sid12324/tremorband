"""Ingest windows, sessions, and passive summaries."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.db import get_session
from app.live import live_hub
from app.models import CaptureSession, Device, PassiveSummary, Window
from app.schemas import (
    IngestBody,
    IngestResult,
    PassiveIn,
    SessionIn,
    WindowIn,
    WindowRead,
    device_to_read,
    utcnow,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["ingest"])


def _upsert_device(session: Session, device_id: str, name: str | None) -> Device:
    device = session.get(Device, device_id)
    if device is None:
        device = Device(id=device_id, name=name or device_id)
        session.add(device)
    elif name:
        device.name = name
    device.last_seen = utcnow()
    session.add(device)
    return device


def _window_payload(row: Window, item: WindowIn) -> dict[str, Any]:
    payload = WindowRead(
        id=row.id or 0,
        device_id=row.device_id,
        ts=row.ts,
        session_id=row.session_id,
        test_type=row.test_type,
        peak_hz=row.peak_hz,
        band_power=row.band_power,
        rms=row.rms,
        sharpness=row.sharpness,
        amp_deg=row.amp_deg,
        disp_mm=row.disp_mm,
        log_amp=row.log_amp,
        label=item.label,
        p_tremor=row.p_tremor,
        vibrating=row.vibrating,
        spectrum=item.spectrum,
        waveform=item.waveform,
    )
    return payload.model_dump(mode="json")


def _apply_session(
    session: Session,
    device_id: str,
    item: SessionIn,
) -> CaptureSession:
    if item.id is None:
        if item.ts_start is None:
            raise HTTPException(status_code=422, detail="ts_start is required for a new session")
        row = CaptureSession(
            device_id=device_id,
            ts_start=item.ts_start,
            ts_end=item.ts_end,
            test_type=item.test_type,
            summary=item.summary,
            quality=item.quality,
            is_synthetic=item.is_synthetic,
        )
        session.add(row)
        session.flush()
        return row

    row = session.get(CaptureSession, item.id)
    if row is None or row.device_id != device_id:
        raise HTTPException(status_code=404, detail=f"session {item.id} not found")
    row.test_type = item.test_type
    if item.ts_start is not None:
        row.ts_start = item.ts_start
    if item.ts_end is not None:
        row.ts_end = item.ts_end
    if item.summary is not None:
        row.summary = item.summary
    if item.quality is not None:
        row.quality = item.quality
    row.is_synthetic = item.is_synthetic
    session.add(row)
    return row


def _apply_window(session: Session, device_id: str, item: WindowIn) -> Window:
    if item.session_id is not None:
        recording = session.get(CaptureSession, item.session_id)
        if recording is None or recording.device_id != device_id:
            raise HTTPException(status_code=404, detail=f"session {item.session_id} not found")
    row = Window(
        device_id=device_id,
        ts=item.ts,
        session_id=item.session_id,
        test_type=item.test_type,
        peak_hz=item.peak_hz,
        band_power=item.band_power,
        rms=item.rms,
        sharpness=item.sharpness,
        amp_deg=item.amp_deg,
        disp_mm=item.disp_mm,
        log_amp=item.log_amp,
        label=item.label,
        p_tremor=item.p_tremor,
        vibrating=item.vibrating,
    )
    session.add(row)
    session.flush()
    return row


def _apply_passive(session: Session, device_id: str, item: PassiveIn) -> PassiveSummary:
    row = PassiveSummary(
        device_id=device_id,
        ts=item.ts,
        tremor_pct=item.tremor_pct,
        median_hz=item.median_hz,
        median_log_amp=item.median_log_amp,
        activity=item.activity,
    )
    session.add(row)
    session.flush()
    return row


@router.post("/ingest", response_model=IngestResult)
def ingest(body: IngestBody, session: Session = Depends(get_session)) -> IngestResult:
    """Store a batch and broadcast each new window on the live stream."""
    device = _upsert_device(session, body.device_id, body.device_name)
    session_ids: list[int] = []
    window_rows: list[tuple[Window, WindowIn]] = []
    passive_ids: list[int] = []

    for item in body.sessions:
        row = _apply_session(session, body.device_id, item)
        if row.id is None:
            raise HTTPException(status_code=500, detail="session id was not assigned")
        session_ids.append(row.id)

    for item in body.windows:
        row = _apply_window(session, body.device_id, item)
        window_rows.append((row, item))

    for item in body.passive_summaries:
        row = _apply_passive(session, body.device_id, item)
        if row.id is None:
            raise HTTPException(status_code=500, detail="passive summary id was not assigned")
        passive_ids.append(row.id)

    session.commit()
    session.refresh(device)
    for row, item in window_rows:
        session.refresh(row)
        live_hub.publish("window", _window_payload(row, item))
    live_hub.publish("device", device_to_read(device).model_dump(mode="json"))

    logger.info(
        "ingest device=%s windows=%d sessions=%d passive=%d",
        body.device_id,
        len(window_rows),
        len(session_ids),
        len(passive_ids),
    )
    return IngestResult(
        device_id=body.device_id,
        window_ids=[row.id for row, _item in window_rows if row.id is not None],
        session_ids=session_ids,
        passive_ids=passive_ids,
    )
