"""Baselines, session comparisons, and the symptom and dose log.

Figures describe stored sessions. They are not a diagnosis and they do not
suggest a dose.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, col, select

from app.analytics import (
    DEFAULT_THRESHOLD_Z,
    DosePoint,
    SessionPoint,
    SymptomPoint,
    WindowPoint,
    adjust_threshold,
    above_threshold,
    baseline_from_points,
    data_quality,
    hours_since_dose,
    session_log_amp,
    session_peak_hz,
    tag_correlations,
    tremor_hours_by_day,
    wearing_off,
    z_score,
)
from app.db import get_session
from app.models import Baseline, CaptureSession, Feedback, Medication, PassiveSummary, SymptomLog, Window
from app.schemas import (
    BaselineRead,
    DemoSeedRead,
    FeedbackIn,
    FeedbackRead,
    MedicationIn,
    MedicationRead,
    QualityReport,
    SessionMetric,
    SessionRead,
    SymptomIn,
    SymptomRead,
    TagCorrelation,
    ThresholdChange,
    TremorHours,
    WearingOffReport,
    as_utc,
    utcnow,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["analytics"])


def _when(value: datetime | None) -> datetime:
    stamped = as_utc(value)
    if stamped is None:
        raise HTTPException(status_code=400, detail="timestamp is required")
    return stamped


def _since(days: int) -> datetime:
    return utcnow() - timedelta(days=days)


def _clean_tag(tag: str) -> str:
    cleaned = " ".join(tag.strip().lower().split())
    if not cleaned or len(cleaned) > 32:
        raise HTTPException(status_code=422, detail="each tag must be 1 to 32 characters")
    return cleaned


def _session_points(rows: list[CaptureSession]) -> list[SessionPoint]:
    points: list[SessionPoint] = []
    for row in rows:
        if row.id is None:
            continue
        points.append(
            SessionPoint(
                session_id=row.id,
                test_type=row.test_type,
                ts=_when(row.ts_start),
                log_amp=session_log_amp(row.summary),
                peak_hz=session_peak_hz(row.summary),
                is_synthetic=row.is_synthetic,
                quality=row.quality,
                device_id=row.device_id,
                ts_end=as_utc(row.ts_end),
            )
        )
    return points


def _dose_points(rows: list[Medication]) -> list[DosePoint]:
    return [DosePoint(ts=_when(row.ts), name=row.name, dose=row.dose) for row in rows]


def _symptom_points(rows: list[SymptomLog]) -> list[SymptomPoint]:
    return [
        SymptomPoint(ts=_when(row.ts), rating=row.rating, tags=list(row.tags or []))
        for row in rows
    ]


def _baseline_read(row: Baseline) -> BaselineRead:
    return BaselineRead(
        test_type=row.test_type,
        mean_log_amp=row.mean_log_amp,
        sd_log_amp=row.sd_log_amp,
        mean_hz=row.mean_hz,
        threshold_z=row.threshold_z,
        n_sessions=row.n_sessions,
        updated_at=_when(row.updated_at),
    )


def persist_baselines(session: Session) -> list[Baseline]:
    """Recompute means and SDs. An adapted threshold_z is kept."""
    points = _session_points(list(session.exec(select(CaptureSession))))
    existing = {row.test_type: row for row in session.exec(select(Baseline))}
    test_types = sorted({point.test_type for point in points if point.log_amp is not None})
    written: list[Baseline] = []
    now = utcnow()
    for test_type in test_types:
        current = existing.get(test_type)
        threshold = current.threshold_z if current is not None else DEFAULT_THRESHOLD_Z
        stats = baseline_from_points(test_type, points, threshold)
        if stats is None:
            continue
        row = current or Baseline(
            test_type=test_type,
            mean_log_amp=stats.mean_log_amp,
            sd_log_amp=stats.sd_log_amp,
            mean_hz=stats.mean_hz,
            threshold_z=stats.threshold_z,
            n_sessions=stats.n_sessions,
            updated_at=now,
        )
        row.mean_log_amp = stats.mean_log_amp
        row.sd_log_amp = stats.sd_log_amp
        row.mean_hz = stats.mean_hz
        row.threshold_z = threshold
        row.n_sessions = stats.n_sessions
        row.updated_at = now
        session.add(row)
        written.append(row)
    return written


def _medication_read(row: Medication) -> MedicationRead:
    if row.id is None:
        raise HTTPException(status_code=500, detail="medication id was not assigned")
    return MedicationRead(id=row.id, ts=_when(row.ts), name=row.name, dose=row.dose)


def _symptom_read(row: SymptomLog) -> SymptomRead:
    if row.id is None:
        raise HTTPException(status_code=500, detail="symptom id was not assigned")
    return SymptomRead(
        id=row.id,
        ts=_when(row.ts),
        rating=row.rating,
        note=row.note,
        tags=list(row.tags or []),
    )


def _session_read(row: CaptureSession) -> SessionRead:
    if row.id is None:
        raise HTTPException(status_code=500, detail="session id was not assigned")
    return SessionRead(
        id=row.id,
        device_id=row.device_id,
        ts_start=_when(row.ts_start),
        ts_end=as_utc(row.ts_end),
        test_type=row.test_type,
        summary=row.summary,
        quality=row.quality,
        is_synthetic=row.is_synthetic,
    )


@router.get("/metrics", response_model=list[SessionMetric])
def get_metrics(
    test_type: str | None = None,
    days: int = Query(default=14, ge=1, le=366),
    session: Session = Depends(get_session),
) -> list[SessionMetric]:
    """Per-session log amplitude, z-score, and hours since the last logged dose."""
    start = _since(days)
    rows = list(session.exec(select(CaptureSession).order_by(col(CaptureSession.ts_start))))
    doses = _dose_points(list(session.exec(select(Medication))))
    baselines = {row.test_type: row for row in session.exec(select(Baseline))}
    metrics: list[SessionMetric] = []
    for row in rows:
        ts = _when(row.ts_start)
        if ts < start:
            continue
        if test_type and row.test_type != test_type:
            continue
        if row.id is None:
            continue
        log_amp = session_log_amp(row.summary)
        baseline = baselines.get(row.test_type)
        score = None
        flagged = False
        if baseline is not None:
            score = z_score(log_amp, baseline.mean_log_amp, baseline.sd_log_amp)
            flagged = above_threshold(score, baseline.threshold_z)
        metrics.append(
            SessionMetric(
                id=row.id,
                device_id=row.device_id,
                test_type=row.test_type,
                ts_start=ts,
                ts_end=as_utc(row.ts_end),
                log_amp=log_amp,
                peak_hz=session_peak_hz(row.summary),
                z=score,
                above_threshold=flagged,
                hours_since_dose=hours_since_dose(ts, doses),
                is_synthetic=row.is_synthetic,
                quality=row.quality,
            )
        )
    return metrics


@router.get("/sessions", response_model=list[SessionRead])
def list_sessions(
    days: int = Query(default=14, ge=1, le=366),
    session: Session = Depends(get_session),
) -> list[SessionRead]:
    """Sessions in the requested window, oldest first."""
    start = _since(days)
    rows = list(session.exec(select(CaptureSession).order_by(col(CaptureSession.ts_start))))
    return [_session_read(row) for row in rows if row.ts_start and _when(row.ts_start) >= start]


@router.get("/sessions/{session_id}", response_model=SessionRead)
def get_session_row(session_id: int, session: Session = Depends(get_session)) -> SessionRead:
    """One stored session."""
    row = session.get(CaptureSession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"session {session_id} not found")
    return _session_read(row)


@router.get("/baseline", response_model=list[BaselineRead])
def get_baseline(session: Session = Depends(get_session)) -> list[BaselineRead]:
    """Personal mean, SD, and comparison line for each test type."""
    rows = list(session.exec(select(Baseline).order_by(Baseline.test_type)))
    return [_baseline_read(row) for row in rows]


@router.post("/baseline/recompute", response_model=list[BaselineRead])
def recompute_baseline(session: Session = Depends(get_session)) -> list[BaselineRead]:
    """Refresh means and SDs from stored sessions and keep each threshold_z."""
    rows = persist_baselines(session)
    session.commit()
    for row in rows:
        logger.info(
            "baseline recomputed test_type=%s n=%d threshold_z=%.2f",
            row.test_type,
            row.n_sessions,
            row.threshold_z,
        )
    return [_baseline_read(row) for row in rows]


@router.post("/medications", response_model=MedicationRead)
def post_medication(body: MedicationIn, session: Session = Depends(get_session)) -> MedicationRead:
    """Store a dose the person already logged."""
    name = body.name.strip()
    dose = body.dose.strip()
    if not name or not dose:
        raise HTTPException(status_code=422, detail="name and dose are required")
    row = Medication(ts=_when(body.ts), name=name, dose=dose)
    session.add(row)
    session.commit()
    session.refresh(row)
    logger.info("medication logged id=%s", row.id)
    return _medication_read(row)


@router.get("/medications", response_model=list[MedicationRead])
def list_medications(
    days: int | None = Query(default=None, ge=1, le=366),
    session: Session = Depends(get_session),
) -> list[MedicationRead]:
    """Logged doses, oldest first."""
    rows = list(session.exec(select(Medication).order_by(col(Medication.ts))))
    if days is None:
        return [_medication_read(row) for row in rows]
    start = _since(days)
    return [_medication_read(row) for row in rows if _when(row.ts) >= start]


@router.post("/symptoms", response_model=SymptomRead)
def post_symptom(body: SymptomIn, session: Session = Depends(get_session)) -> SymptomRead:
    """Store a self-reported rating and tags."""
    tags = [_clean_tag(tag) for tag in body.tags]
    note = body.note.strip() if body.note else None
    row = SymptomLog(ts=_when(body.ts), rating=body.rating, note=note or None, tags=tags)
    session.add(row)
    session.commit()
    session.refresh(row)
    logger.info("symptom logged id=%s rating=%s tags=%s", row.id, row.rating, tags)
    return _symptom_read(row)


@router.get("/symptoms", response_model=list[SymptomRead])
def list_symptoms(
    days: int | None = Query(default=None, ge=1, le=366),
    session: Session = Depends(get_session),
) -> list[SymptomRead]:
    """Symptom-log entries, oldest first."""
    rows = list(session.exec(select(SymptomLog).order_by(col(SymptomLog.ts))))
    if days is None:
        return [_symptom_read(row) for row in rows]
    start = _since(days)
    return [_symptom_read(row) for row in rows if _when(row.ts) >= start]


@router.post("/feedback", response_model=FeedbackRead)
def post_feedback(body: FeedbackIn, session: Session = Depends(get_session)) -> FeedbackRead:
    """Move threshold_z by one step and log the reason."""
    capture: CaptureSession | None = None
    if body.session_id is not None:
        capture = session.get(CaptureSession, body.session_id)
        if capture is None:
            raise HTTPException(status_code=404, detail=f"session {body.session_id} not found")
    row = Feedback(ts=_when(body.ts), session_id=body.session_id, kind=body.kind)
    session.add(row)
    targets: list[Baseline] = []
    if capture is not None:
        existing = session.get(Baseline, capture.test_type)
        if existing is None:
            existing = Baseline(
                test_type=capture.test_type,
                mean_log_amp=0.0,
                sd_log_amp=0.0,
                mean_hz=0.0,
                threshold_z=DEFAULT_THRESHOLD_Z,
                n_sessions=0,
                updated_at=utcnow(),
            )
            logger.info("created baseline %s so feedback can move threshold_z", capture.test_type)
        targets = [existing]
    else:
        targets = list(session.exec(select(Baseline)))
    changes: list[ThresholdChange] = []
    now = utcnow()
    for baseline in targets:
        update = adjust_threshold(baseline.threshold_z, body.kind)
        logger.info("threshold change test_type=%s reason=%s", baseline.test_type, update.reason)
        baseline.threshold_z = update.new_threshold_z
        baseline.updated_at = now
        session.add(baseline)
        changes.append(
            ThresholdChange(
                test_type=baseline.test_type,
                old_threshold_z=update.old_threshold_z,
                new_threshold_z=update.new_threshold_z,
                reason=update.reason,
            )
        )
    if not targets:
        logger.info("feedback %s stored with no baseline to adjust", body.kind)
    session.commit()
    session.refresh(row)
    if row.id is None:
        raise HTTPException(status_code=500, detail="feedback id was not assigned")
    return FeedbackRead(
        id=row.id,
        ts=_when(row.ts),
        session_id=row.session_id,
        kind=body.kind,
        changes=changes,
    )


def _window_points(session: Session, days: int) -> list[WindowPoint]:
    start = _since(days)
    rows = list(session.exec(select(Window)))
    chosen: list[WindowPoint] = []
    for row in rows:
        if _when(row.ts) < start:
            continue
        chosen.append(
            WindowPoint(
                vibrating=row.vibrating,
                log_amp=row.log_amp,
                peak_hz=row.peak_hz,
                label=row.label,
                rms=row.rms,
            )
        )
    return chosen


@router.get("/analytics/wearing-off", response_model=WearingOffReport)
def get_wearing_off(
    days: int = Query(default=14, ge=1, le=366),
    session: Session = Depends(get_session),
) -> WearingOffReport:
    """Compare log amplitude 3 to 5 hours after a logged dose with the first 2 hours."""
    start = _since(days)
    rows = [row for row in session.exec(select(CaptureSession)) if _when(row.ts_start) >= start]
    report = wearing_off(_session_points(list(rows)), _dose_points(list(session.exec(select(Medication)))))
    return WearingOffReport.model_validate(report)


@router.get("/analytics/tags", response_model=list[TagCorrelation])
def get_tags(
    days: int = Query(default=14, ge=1, le=366),
    session: Session = Depends(get_session),
) -> list[TagCorrelation]:
    """Association between symptom tags and recorded log amplitude."""
    start = _since(days)
    rows = [row for row in session.exec(select(CaptureSession)) if _when(row.ts_start) >= start]
    symptoms = [row for row in session.exec(select(SymptomLog)) if _when(row.ts) >= start]
    reports = tag_correlations(_session_points(list(rows)), _symptom_points(list(symptoms)))
    return [TagCorrelation.model_validate(item) for item in reports]


@router.get("/analytics/quality", response_model=QualityReport)
def get_quality(
    days: int = Query(default=14, ge=1, le=366),
    session: Session = Depends(get_session),
) -> QualityReport:
    """Windows left out for vibration, missing fields, or an empty signal."""
    return QualityReport.model_validate(data_quality(_window_points(session, days)))


@router.get("/analytics/tremor-hours", response_model=list[TremorHours])
def get_tremor_hours(
    days: int = Query(default=14, ge=1, le=366),
    session: Session = Depends(get_session),
) -> list[TremorHours]:
    """Passive tremor percent rolled into hours per day. A row covers the gap until the next row, up to one hour."""
    start = _since(days)
    rows = [
        (_when(row.ts), row.tremor_pct)
        for row in session.exec(select(PassiveSummary))
        if _when(row.ts) >= start
    ]
    return [TremorHours.model_validate(item) for item in tremor_hours_by_day(rows)]


@router.post("/demo/reset", response_model=DemoSeedRead)
def reset_demo(session: Session = Depends(get_session)) -> DemoSeedRead:
    """Replace the synthetic demo band and reseed seven days. Other bands stay."""
    from scripts.seed_demo import seed_database

    summary = seed_database(session, reset=True)
    logger.info("demo reset sessions=%s", summary["sessions"])
    return DemoSeedRead.model_validate(summary)
