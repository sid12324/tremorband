"""Request and response models for the milestone 1 API."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models import Device

CONNECTED_WITHIN_S = 20.0
Label = Literal["still", "voluntary", "tremor"]
CreatedBy = Literal["user", "agent"]


def as_utc(value: datetime | None) -> datetime | None:
    """Attach UTC to naive timestamps coming back from SQLite."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def utcnow() -> datetime:
    """Current time in UTC."""
    return datetime.now(timezone.utc)


class SpectrumBin(BaseModel):
    """One display bin. It is broadcast live and not stored."""

    hz: float = Field(ge=0, le=30)
    power: float = Field(ge=0)


class WindowIn(BaseModel):
    """One posted feature window."""

    ts: datetime
    session_id: int | None = None
    test_type: str | None = Field(default=None, max_length=64)
    peak_hz: float
    band_power: float = Field(ge=0)
    rms: float = Field(ge=0)
    sharpness: float = Field(ge=0)
    amp_deg: float = Field(ge=0)
    disp_mm: float = Field(ge=0)
    log_amp: float
    label: Label
    p_tremor: float = Field(ge=0, le=1)
    vibrating: bool = False
    spectrum: list[SpectrumBin] | None = Field(default=None, max_length=128)
    waveform: list[float] | None = Field(default=None, max_length=256)


class SessionIn(BaseModel):
    """Create or update a session row."""

    id: int | None = None
    ts_start: datetime | None = None
    ts_end: datetime | None = None
    test_type: str = Field(min_length=1, max_length=64)
    summary: dict[str, Any] | None = None
    quality: float | None = Field(default=None, ge=0, le=1)
    is_synthetic: bool = False


class PassiveIn(BaseModel):
    """One passive-monitoring summary."""

    ts: datetime
    tremor_pct: float = Field(ge=0, le=100)
    median_hz: float = Field(ge=0)
    median_log_amp: float
    activity: float = Field(ge=0)


class IngestBody(BaseModel):
    """Batch posted by a band or the simulator."""

    device_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._:-]+$")
    device_name: str | None = Field(default=None, max_length=80)
    windows: list[WindowIn] = Field(default_factory=list, max_length=200)
    sessions: list[SessionIn] = Field(default_factory=list, max_length=20)
    passive_summaries: list[PassiveIn] = Field(default_factory=list, max_length=50)


class IngestResult(BaseModel):
    """Identifiers created or updated by an ingest call."""

    device_id: str
    window_ids: list[int]
    session_ids: list[int]
    passive_ids: list[int]


class HeartbeatIn(BaseModel):
    """Status posted by a band."""

    name: str | None = Field(default=None, max_length=80)
    battery: float | None = Field(default=None, ge=0, le=100)
    rssi: float | None = Field(default=None, ge=-120, le=0)
    fw_version: str | None = Field(default=None, max_length=40)
    mode: str | None = Field(default=None, max_length=32)
    uptime_s: float | None = Field(default=None, ge=0)


class CommandIn(BaseModel):
    """Command created from the Live page."""

    device_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._:-]+$")
    cmd: str = Field(min_length=1, max_length=120)
    created_by: CreatedBy = "user"
    reason: str | None = Field(default=None, max_length=200)


class CommandRead(BaseModel):
    """Command row returned to a band or the Live page."""

    id: int
    device_id: str
    cmd: str
    status: Literal["pending", "sent", "done"]
    created_by: CreatedBy
    reason: str | None


class DeviceRead(BaseModel):
    """Device status, including whether the last contact is recent."""

    id: str
    name: str
    last_seen: datetime | None
    battery: float | None
    rssi: float | None
    fw_version: str | None
    mode: str | None
    connected: bool


class WindowRead(BaseModel):
    """Stored window features. Spectrum and waveform are live-only."""

    id: int
    device_id: str
    ts: datetime
    session_id: int | None
    test_type: str | None
    peak_hz: float
    band_power: float
    rms: float
    sharpness: float
    amp_deg: float
    disp_mm: float
    log_amp: float
    label: Label
    p_tremor: float
    vibrating: bool
    spectrum: list[SpectrumBin] | None = None
    waveform: list[float] | None = None


def device_connected(last_seen: datetime | None, now: datetime | None = None) -> bool:
    """True when the band has checked in within the last 20 seconds."""
    seen = as_utc(last_seen)
    if seen is None:
        return False
    current = now or utcnow()
    return (current - seen).total_seconds() <= CONNECTED_WITHIN_S


def device_to_read(device: Device) -> DeviceRead:
    """Map a device row to the API response."""
    return DeviceRead(
        id=device.id,
        name=device.name,
        last_seen=as_utc(device.last_seen),
        battery=device.battery,
        rssi=device.rssi,
        fw_version=device.fw_version,
        mode=device.mode,
        connected=device_connected(device.last_seen),
    )
