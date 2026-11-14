"""Calibration rig runs and accuracy."""

from __future__ import annotations

import logging
from collections import defaultdict

from fastapi import APIRouter, Depends
from sqlmodel import Session, col, select

from app.db import get_session
from app.models import RigRun
from app.schemas import RigAccuracy, RigFrequencyRow, RigPoint, RigRunIn, RigRunRead, as_utc

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["rig"])

ACCURACY_LIMIT = 500


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _compared(run: RigRun) -> float | None:
    if run.band_hz is not None:
        return run.band_hz
    return run.measured_hz


def record_run(body: RigRunIn, session: Session) -> RigRunRead:
    """Store one rig setpoint and the measurement paired with it."""
    row = RigRun(
        ts=body.ts,
        set_hz=body.set_hz,
        measured_hz=body.measured_hz,
        band_hz=body.band_hz,
        amp_set=body.amp_set,
        amp_band=body.amp_band,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    if row.id is None:
        raise RuntimeError("rig run id was not assigned")
    logger.info("rig run set_hz=%.3f band_hz=%s measured_hz=%s", row.set_hz, row.band_hz, row.measured_hz)
    return _read(row)


def _read(row: RigRun) -> RigRunRead:
    return RigRunRead(
        id=row.id or 0,
        ts=as_utc(row.ts) or row.ts,
        set_hz=row.set_hz,
        measured_hz=row.measured_hz,
        band_hz=row.band_hz,
        amp_set=row.amp_set,
        amp_band=row.amp_band,
    )


@router.post("/rig/run", response_model=RigRunRead)
def post_run(body: RigRunIn, session: Session = Depends(get_session)) -> RigRunRead:
    """Record a setpoint from the Calibration page or a rig serial line."""
    return record_run(body, session)


@router.get("/rig/accuracy", response_model=RigAccuracy)
def accuracy(session: Session = Depends(get_session)) -> RigAccuracy:
    """MAE, percent error per setpoint, and scatter points.

    A run is compared with band_hz when that was paired, otherwise measured_hz.
    """
    stored = session.exec(select(RigRun).order_by(col(RigRun.id).desc()).limit(ACCURACY_LIMIT)).all()
    runs = list(reversed(stored))
    points: list[RigPoint] = []
    grouped: dict[float, list[RigRun]] = defaultdict(list)
    for run in runs:
        compared = _compared(run)
        if compared is None or run.id is None or run.set_hz == 0:
            continue
        error = compared - run.set_hz
        points.append(
            RigPoint(
                id=run.id,
                ts=as_utc(run.ts) or run.ts,
                set_hz=run.set_hz,
                measured_hz=run.measured_hz,
                band_hz=run.band_hz,
                compared_hz=compared,
                error_hz=error,
                error_pct=error / run.set_hz * 100.0,
                amp_set=run.amp_set,
                amp_band=run.amp_band,
            )
        )
        grouped[round(run.set_hz, 2)].append(run)

    rows: list[RigFrequencyRow] = []
    for set_hz in sorted(grouped):
        group = grouped[set_hz]
        errors = []
        percents = []
        for run in group:
            compared = _compared(run)
            if compared is None:
                continue
            error = compared - run.set_hz
            errors.append(abs(error))
            percents.append(error / run.set_hz * 100.0)
        rows.append(
            RigFrequencyRow(
                set_hz=set_hz,
                n=len(errors),
                mean_band_hz=_mean([run.band_hz for run in group if run.band_hz is not None]),
                mean_measured_hz=_mean([run.measured_hz for run in group if run.measured_hz is not None]),
                mae_hz=_mean(errors) or 0.0,
                mean_pct_error=_mean(percents) or 0.0,
            )
        )
    absolute = [abs(point.error_hz) for point in points]
    return RigAccuracy(
        mae_hz=_mean(absolute),
        n=len(points),
        rows=rows,
        points=points,
    )
