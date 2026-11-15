"""Laptop capture switch.

Turning capture on opens a new session. Turning it off closes that session.
Windows ingested while a session is open, and that do not already name a
session, are stored on the open session.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Session, col, select

from app.models import CaptureSession, Device, Window
from app.schemas import as_utc, utcnow

CAPTURE_TYPE = "capture"
LOCAL_DEVICE_ID = "local"


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _round(value: float | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    return round(value, digits)


def open_capture(session: Session) -> CaptureSession | None:
    """The capture session that is still accepting windows, if one is open."""
    return session.exec(
        select(CaptureSession)
        .where(CaptureSession.test_type == CAPTURE_TYPE)
        .where(col(CaptureSession.ts_end).is_(None))
        .order_by(col(CaptureSession.id).desc())
    ).first()


def _device_id(session: Session) -> str:
    rows = list(session.exec(select(Device)))
    seen = [row for row in rows if as_utc(row.last_seen) is not None]
    if seen:
        seen.sort(key=lambda row: as_utc(row.last_seen) or datetime.min.replace(tzinfo=timezone.utc))
        return seen[-1].id
    if rows:
        return rows[0].id
    device = Device(id=LOCAL_DEVICE_ID, name="This laptop", mode="capture")
    session.add(device)
    session.flush()
    return LOCAL_DEVICE_ID


def measurements(session: Session, row: CaptureSession) -> dict[str, float | int | None]:
    """Numbers stored for one session. Vibration windows stay out of the medians."""
    windows = list(session.exec(select(Window).where(Window.session_id == row.id)))
    usable = [item for item in windows if not item.vibrating]
    summary = row.summary or {}
    peak_values = [item.peak_hz for item in usable]
    amp_values = [item.amp_deg for item in usable]
    log_values = [item.log_amp for item in usable]
    tremor = [item for item in usable if item.label == "tremor"]
    peak = _median(peak_values)
    amp = _median(amp_values)
    log_amp = _median(log_values)
    if peak is None and summary.get("median_hz") is not None:
        peak = float(summary["median_hz"])
    if peak is None and summary.get("median_peak_hz") is not None:
        peak = float(summary["median_peak_hz"])
    if log_amp is None and summary.get("median_log_amp") is not None:
        log_amp = float(summary["median_log_amp"])
    tremor_pct = (100.0 * len(tremor) / len(usable)) if usable else None
    if tremor_pct is None and summary.get("tremor_pct") is not None:
        tremor_pct = float(summary["tremor_pct"])
    mean_p = (sum(item.p_tremor for item in usable) / len(usable)) if usable else None
    if mean_p is None and summary.get("mean_p_tremor") is not None:
        mean_p = float(summary["mean_p_tremor"])
    return {
        "n_windows": len(windows),
        "n_usable": len(usable),
        "n_tremor": len(tremor),
        "n_still": sum(1 for item in usable if item.label == "still"),
        "n_voluntary": sum(1 for item in usable if item.label == "voluntary"),
        "excluded_vibration": len(windows) - len(usable),
        "median_peak_hz": _round(peak),
        "median_amp_deg": _round(amp),
        "median_log_amp": _round(log_amp),
        "mean_p_tremor": _round(mean_p),
        "tremor_pct": _round(tremor_pct, 1),
    }


def start_capture(session: Session) -> CaptureSession:
    """Open a new capture session. An already open session stays open."""
    current = open_capture(session)
    if current is not None:
        return current
    row = CaptureSession(
        device_id=_device_id(session),
        ts_start=utcnow(),
        ts_end=None,
        test_type=CAPTURE_TYPE,
        summary=None,
        quality=None,
        is_synthetic=False,
    )
    session.add(row)
    session.flush()
    return row


def stop_capture(session: Session) -> CaptureSession | None:
    """End the open capture session and store its window numbers."""
    current = open_capture(session)
    if current is None:
        return None
    stats = measurements(session, current)
    current.ts_end = utcnow()
    current.summary = {key: value for key, value in stats.items()}
    total = int(stats["n_windows"] or 0)
    usable = int(stats["n_usable"] or 0)
    current.quality = (usable / total) if total else None
    session.add(current)
    session.flush()
    return current


def assign_open_session(session: Session, session_id: int | None) -> int | None:
    """Use the open capture session when an ingested window does not name one."""
    if session_id is not None:
        return session_id
    current = open_capture(session)
    if current is None or current.id is None:
        return None
    return current.id


def allows_device(recording: CaptureSession, device_id: str) -> bool:
    """The open capture session accepts windows from whichever band is posting."""
    if recording.device_id == device_id:
        return True
    return recording.test_type == CAPTURE_TYPE and recording.ts_end is None
