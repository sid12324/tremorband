"""Passive rows, preferences, CSV export, and delete-my-data."""

from __future__ import annotations

import csv
import io
import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlmodel import Session, SQLModel, col, select

from app.db import get_session
from app.models import (
    AgentEvent,
    Baseline,
    CaptureSession,
    CareSettings,
    Command,
    Device,
    Feedback,
    Medication,
    PassiveSummary,
    Report,
    RigRun,
    SymptomLog,
    Window,
)
from app.schemas import as_utc, utcnow

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["records"])

DELETE_PHRASE = "delete my data"


class SettingsIn(BaseModel):
    """Preferences the planner and the Settings page share."""

    transport: str = Field(default="simulator", pattern="^(wifi|serial|simulator)$")
    ms_mode: bool = False
    sleep_start_hour: int = Field(default=22, ge=0, le=23)
    sleep_end_hour: int = Field(default=7, ge=0, le=23)
    haptic_intensity: int = Field(default=70, ge=0, le=100)


class SettingsRead(SettingsIn):
    """Stored preferences."""


class DeleteIn(BaseModel):
    """The exact phrase is required so a stray click cannot empty the log."""

    confirm: str


def _settings_row(session: Session) -> CareSettings:
    row = session.get(CareSettings, 1)
    if row is None:
        row = CareSettings(id=1)
        session.add(row)
        session.commit()
        session.refresh(row)
    return row


def _settings_read(row: CareSettings) -> SettingsRead:
    return SettingsRead(
        transport=row.transport,
        ms_mode=row.ms_mode,
        sleep_start_hour=row.sleep_start_hour,
        sleep_end_hour=row.sleep_end_hour,
        haptic_intensity=row.haptic_intensity,
    )


@router.get("/settings", response_model=SettingsRead)
def get_settings(session: Session = Depends(get_session)) -> SettingsRead:
    """Sleep hours, mode, and the recorded transport."""
    return _settings_read(_settings_row(session))


@router.put("/settings", response_model=SettingsRead)
def put_settings(body: SettingsIn, session: Session = Depends(get_session)) -> SettingsRead:
    """Save preferences. This does not suggest a dose."""
    row = _settings_row(session)
    row.transport = body.transport
    row.ms_mode = body.ms_mode
    row.sleep_start_hour = body.sleep_start_hour
    row.sleep_end_hour = body.sleep_end_hour
    row.haptic_intensity = body.haptic_intensity
    session.add(row)
    session.commit()
    session.refresh(row)
    logger.info("settings saved transport=%s ms_mode=%s", row.transport, row.ms_mode)
    return _settings_read(row)


@router.get("/passive")
def list_passive(
    days: int = 1,
    session: Session = Depends(get_session),
) -> list[dict]:
    """Recent passive summaries. Each row is one compact monitoring interval."""
    start = utcnow() - timedelta(days=max(1, min(days, 90)))
    rows = [
        row
        for row in session.exec(select(PassiveSummary).order_by(col(PassiveSummary.ts)))
        if as_utc(row.ts) and as_utc(row.ts) >= start
    ]
    return [
        {
            "id": row.id,
            "device_id": row.device_id,
            "ts": as_utc(row.ts).isoformat() if as_utc(row.ts) else None,
            "tremor_pct": row.tremor_pct,
            "median_hz": row.median_hz,
            "median_log_amp": row.median_log_amp,
            "activity": row.activity,
        }
        for row in rows[-200:]
    ]


@router.get("/export.csv")
def export_csv(session: Session = Depends(get_session)) -> Response:
    """Download the log as CSV. One section per table."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    tables: list[tuple[str, type[SQLModel]]] = [
        ("devices", Device),
        ("sessions", CaptureSession),
        ("windows", Window),
        ("passive_summaries", PassiveSummary),
        ("medications", Medication),
        ("symptom_log", SymptomLog),
        ("baseline", Baseline),
        ("feedback", Feedback),
        ("reports", Report),
        ("commands", Command),
        ("rig_runs", RigRun),
        ("agent_events", AgentEvent),
        ("care_settings", CareSettings),
    ]
    for name, model in tables:
        rows = list(session.exec(select(model)))
        writer.writerow([f"# {name}"])
        columns = list(model.__table__.columns.keys())  # type: ignore[attr-defined]
        writer.writerow(columns)
        for row in rows:
            writer.writerow([getattr(row, column) for column in columns])
        writer.writerow([])
    logger.info("csv export written")
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="tremorband.csv"'},
    )


@router.delete("/data")
def delete_data(body: DeleteIn, session: Session = Depends(get_session)) -> dict[str, str]:
    """Remove stored rows after the person types the confirmation phrase."""
    if body.confirm.strip().lower() != DELETE_PHRASE:
        raise HTTPException(status_code=400, detail=f'Type "{DELETE_PHRASE}" to confirm.')
    from sqlmodel import delete

    for model in (
        Feedback,
        Window,
        Command,
        PassiveSummary,
        CaptureSession,
        Medication,
        SymptomLog,
        Report,
        AgentEvent,
        Baseline,
        RigRun,
        Device,
        CareSettings,
    ):
        session.exec(delete(model))
    session.commit()
    logger.info("stored rows deleted at the person's request")
    return {"deleted": "all stored rows"}
