"""SQLite tables for TremorBand.

The rows store monitoring measurements. They are not a diagnosis.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, Column
from sqlmodel import Field, SQLModel


class Device(SQLModel, table=True):
    """A band that posts windows and heartbeats."""

    __tablename__ = "devices"

    id: str = Field(primary_key=True)
    name: str
    last_seen: datetime | None = None
    battery: float | None = None
    rssi: float | None = None
    fw_version: str | None = None
    mode: str | None = None


class CaptureSession(SQLModel, table=True):
    """One guided-test recording."""

    __tablename__ = "sessions"

    id: int | None = Field(default=None, primary_key=True)
    device_id: str = Field(foreign_key="devices.id", index=True)
    ts_start: datetime
    ts_end: datetime | None = None
    test_type: str
    summary: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    quality: float | None = None
    is_synthetic: bool = False


class Window(SQLModel, table=True):
    """Features for one analysis window."""

    __tablename__ = "windows"
    __table_args__ = (
        CheckConstraint(
            "label IN ('still', 'voluntary', 'tremor')",
            name="ck_window_label",
        ),
        CheckConstraint(
            "p_tremor >= 0 AND p_tremor <= 1",
            name="ck_window_p_tremor",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    device_id: str = Field(foreign_key="devices.id", index=True)
    ts: datetime = Field(index=True)
    session_id: int | None = Field(default=None, foreign_key="sessions.id", index=True)
    test_type: str | None = None
    peak_hz: float
    band_power: float
    rms: float
    sharpness: float
    amp_deg: float
    disp_mm: float
    log_amp: float
    label: str
    p_tremor: float
    vibrating: bool = False


class PassiveSummary(SQLModel, table=True):
    """Compact passive-monitoring summary."""

    __tablename__ = "passive_summaries"

    id: int | None = Field(default=None, primary_key=True)
    device_id: str = Field(foreign_key="devices.id", index=True)
    ts: datetime = Field(index=True)
    tremor_pct: float
    median_hz: float
    median_log_amp: float
    activity: float


class Medication(SQLModel, table=True):
    """A logged dose. The API does not interpret it."""

    __tablename__ = "medications"

    id: int | None = Field(default=None, primary_key=True)
    ts: datetime = Field(index=True)
    name: str
    dose: str


class SymptomLog(SQLModel, table=True):
    """A self-reported symptom rating and tags."""

    __tablename__ = "symptom_log"
    __table_args__ = (
        CheckConstraint("rating >= 0 AND rating <= 4", name="ck_symptom_rating"),
    )

    id: int | None = Field(default=None, primary_key=True)
    ts: datetime = Field(index=True)
    rating: int
    note: str | None = None
    tags: list[str] | None = Field(default=None, sa_column=Column(JSON))


class Baseline(SQLModel, table=True):
    """Personal baseline statistics for one test type."""

    __tablename__ = "baseline"

    test_type: str = Field(primary_key=True)
    mean_log_amp: float
    sd_log_amp: float
    mean_hz: float
    threshold_z: float = 2.0
    n_sessions: int = 0
    updated_at: datetime


class Feedback(SQLModel, table=True):
    """User feedback attached to a session."""

    __tablename__ = "feedback"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('not_a_bad_day', 'missed_symptoms')",
            name="ck_feedback_kind",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    ts: datetime
    session_id: int | None = Field(default=None, foreign_key="sessions.id")
    kind: str


class Command(SQLModel, table=True):
    """A command queued for a band."""

    __tablename__ = "commands"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'sent', 'done')",
            name="ck_command_status",
        ),
        CheckConstraint(
            "created_by IN ('user', 'agent')",
            name="ck_command_created_by",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    device_id: str = Field(foreign_key="devices.id", index=True)
    cmd: str
    status: str = "pending"
    created_by: str
    reason: str | None = None


class Report(SQLModel, table=True):
    """A clinician report draft. Milestone 1 does not generate these."""

    __tablename__ = "reports"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'approved', 'sent', 'rejected')",
            name="ck_report_status",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime
    markdown: str
    status: str
    recipient: str | None = None


class RigRun(SQLModel, table=True):
    """Calibration-rig setpoint paired with a band measurement."""

    __tablename__ = "rig_runs"

    id: int | None = Field(default=None, primary_key=True)
    ts: datetime
    set_hz: float
    measured_hz: float | None = None
    band_hz: float | None = None
    amp_set: float | None = None
    amp_band: float | None = None


class AgentEvent(SQLModel, table=True):
    """Timeline event for a later agent run."""

    __tablename__ = "agent_events"

    id: int | None = Field(default=None, primary_key=True)
    run_id: str = Field(index=True)
    ts: datetime
    type: str
    payload: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
