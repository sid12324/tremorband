"""Device status, heartbeats, commands, and stored windows."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, col, select

from app.db import get_session
from app.live import live_hub
from app.models import Command, Device, Window
from app.schemas import (
    CommandIn,
    CommandRead,
    DeviceRead,
    HeartbeatIn,
    WindowRead,
    device_to_read,
    utcnow,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["devices"])


def _require_device(session: Session, device_id: str) -> Device:
    device = session.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail=f"device {device_id} not found")
    return device


def _command_read(row: Command) -> CommandRead:
    if row.id is None:
        raise HTTPException(status_code=500, detail="command id was not assigned")
    return CommandRead(
        id=row.id,
        device_id=row.device_id,
        cmd=row.cmd,
        status=row.status,  # type: ignore[arg-type]
        created_by=row.created_by,  # type: ignore[arg-type]
        reason=row.reason,
    )


def _window_read(row: Window) -> WindowRead:
    if row.id is None:
        raise HTTPException(status_code=500, detail="window id was not assigned")
    return WindowRead(
        id=row.id,
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
        label=row.label,  # type: ignore[arg-type]
        p_tremor=row.p_tremor,
        vibrating=row.vibrating,
    )


@router.get("/devices", response_model=list[DeviceRead])
def list_devices(session: Session = Depends(get_session)) -> list[DeviceRead]:
    """List bands, most recently seen first."""
    rows = session.exec(select(Device).order_by(col(Device.last_seen).desc())).all()
    return [device_to_read(row) for row in rows]


@router.get("/device/{device_id}", response_model=DeviceRead)
def get_device(device_id: str, session: Session = Depends(get_session)) -> DeviceRead:
    """Return one band's latest status."""
    return device_to_read(_require_device(session, device_id))


@router.get("/device/{device_id}/latest", response_model=WindowRead | None)
def latest_window(device_id: str) -> WindowRead | None:
    """Return the newest live window, including its spectrum, when one is cached."""
    payload = live_hub.latest_window(device_id)
    if payload is None:
        return None
    return WindowRead.model_validate(payload)


@router.post("/device/{device_id}/heartbeat", response_model=DeviceRead)
def heartbeat(
    device_id: str,
    body: HeartbeatIn,
    session: Session = Depends(get_session),
) -> DeviceRead:
    """Update band status and broadcast it."""
    device = session.get(Device, device_id)
    if device is None:
        device = Device(id=device_id, name=body.name or device_id)
        session.add(device)
    if body.name:
        device.name = body.name
    device.last_seen = utcnow()
    if body.battery is not None:
        device.battery = body.battery
    if body.rssi is not None:
        device.rssi = body.rssi
    if body.fw_version is not None:
        device.fw_version = body.fw_version
    if body.mode is not None:
        device.mode = body.mode
    session.add(device)
    session.commit()
    session.refresh(device)
    payload = device_to_read(device)
    live_hub.publish("device", payload.model_dump(mode="json"))
    logger.info(
        "heartbeat device=%s battery=%s rssi=%s mode=%s uptime_s=%s",
        device_id,
        body.battery,
        body.rssi,
        body.mode,
        body.uptime_s,
    )
    return payload


@router.post("/commands", response_model=CommandRead)
def create_command(body: CommandIn, session: Session = Depends(get_session)) -> CommandRead:
    """Queue a command for a band that has already checked in."""
    _require_device(session, body.device_id)
    row = Command(
        device_id=body.device_id,
        cmd=body.cmd,
        status="pending",
        created_by=body.created_by,
        reason=body.reason,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    payload = _command_read(row)
    live_hub.publish("command", payload.model_dump(mode="json"))
    logger.info("command queued device=%s cmd=%s by=%s", body.device_id, body.cmd, body.created_by)
    return payload


@router.get("/device/{device_id}/commands", response_model=list[CommandRead])
def poll_commands(device_id: str, session: Session = Depends(get_session)) -> list[CommandRead]:
    """Return pending commands and mark them sent."""
    _require_device(session, device_id)
    rows = session.exec(
        select(Command)
        .where(Command.device_id == device_id, Command.status == "pending")
        .order_by(col(Command.id))
    ).all()
    sent: list[CommandRead] = []
    for row in rows:
        row.status = "sent"
        session.add(row)
    session.commit()
    for row in rows:
        session.refresh(row)
        payload = _command_read(row)
        sent.append(payload)
        live_hub.publish("command", payload.model_dump(mode="json"))
    if sent:
        logger.info("commands sent device=%s count=%d", device_id, len(sent))
    return sent


@router.get("/windows", response_model=list[WindowRead])
def list_windows(
    device_id: str,
    limit: int = Query(default=40, ge=1, le=500),
    session: Session = Depends(get_session),
) -> list[WindowRead]:
    """Return the newest stored windows in chronological order."""
    _require_device(session, device_id)
    rows = session.exec(
        select(Window)
        .where(Window.device_id == device_id)
        .order_by(col(Window.ts).desc(), col(Window.id).desc())
        .limit(limit)
    ).all()
    return [_window_read(row) for row in reversed(rows)]
