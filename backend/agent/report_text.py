"""Clinician note assembled from stored numbers.

The note describes recordings. It does not diagnose and it does not suggest a dose.
"""

from __future__ import annotations

from sqlmodel import Session, select

from app.analytics import (
    data_quality,
    session_log_amp,
    session_peak_hz,
    tag_correlations,
    tremor_hours_by_day,
    wearing_off,
)
from app.models import CaptureSession, Medication, PassiveSummary, SymptomLog
from app.routes.analytics import _dose_points, _session_points, _symptom_points, _window_points
from app.schemas import as_utc

DISCLAIMER = "TremorBand is a monitoring aid, not a diagnostic device."
REPORT_LINE = "Monitoring aid, not a diagnosis."


def compose_report(session: Session, days: int = 14) -> str:
    """Build the one-page note from the log."""
    from datetime import timedelta

    from app.schemas import utcnow

    start = utcnow() - timedelta(days=days)
    captures = [
        row
        for row in session.exec(select(CaptureSession))
        if as_utc(row.ts_start) is not None and as_utc(row.ts_start) >= start
    ]
    points = _session_points(captures)
    doses = _dose_points(list(session.exec(select(Medication))))
    symptoms = _symptom_points(
        [row for row in session.exec(select(SymptomLog)) if as_utc(row.ts) and as_utc(row.ts) >= start]
    )
    timing = wearing_off(points, doses)
    tags = tag_correlations(points, symptoms)
    quality = data_quality(_window_points(session, days))
    passive = [
        (as_utc(row.ts), row.tremor_pct)
        for row in session.exec(select(PassiveSummary))
        if as_utc(row.ts) and as_utc(row.ts) >= start
    ]
    hours = tremor_hours_by_day([(ts, pct) for ts, pct in passive if ts is not None])
    synthetic = any(point.is_synthetic for point in points)
    lines = [
        "# TremorBand clinician note",
        "",
        DISCLAIMER,
        "",
        REPORT_LINE,
        "",
        "Share this note with the person's clinician. It is a record of sessions, not a treatment plan.",
        "",
        "## Summary",
        "",
        f"Sessions in the last {days} days: {len(points)}.",
    ]
    if synthetic:
        lines.append("Some of these sessions are simulated and are marked synthetic in the log.")
    usable = [point for point in points if point.log_amp is not None]
    if usable:
        mean_amp = sum(point.log_amp or 0.0 for point in usable) / len(usable)
        lines.append(f"Mean log amplitude across those sessions: {mean_amp:.2f}.")
    if hours:
        latest = hours[-1]
        lines.append(
            f"Passive tremor time on {latest['day']}: {float(latest['tremor_hours']):.2f} hours "
            f"from {int(latest['n'])} summaries."
        )
    lines.extend(["", "## Session metrics", "", "| Test | When | Log amplitude | Peak Hz | Synthetic |", "| --- | --- | --- | --- | --- |"])
    for point in points[-12:]:
        amp = "" if point.log_amp is None else f"{point.log_amp:.2f}"
        peak = "" if point.peak_hz is None else f"{point.peak_hz:.2f}"
        lines.append(
            f"| {point.test_type} | {point.ts.strftime('%Y-%m-%d %H:%M')} | {amp} | {peak} | "
            f"{'yes' if point.is_synthetic else 'no'} |"
        )
    lines.extend(
        [
            "",
            "## Timing of logged doses",
            "",
            str(timing["finding"]),
            f"Confidence: {timing['confidence']}.",
            "",
            "## Symptom log",
            "",
        ]
    )
    if not symptoms:
        lines.append("No symptom-log entries in this window.")
    for symptom in symptoms[-8:]:
        tag_text = ", ".join(symptom.tags) if symptom.tags else "no tags"
        lines.append(f"- {symptom.ts.strftime('%Y-%m-%d %H:%M')} rating {symptom.rating} ({tag_text}).")
    for tag in tags:
        lines.append(str(tag["finding"]))
    used = quality["n_used"]
    total = quality["n_windows"]
    lines.extend(
        [
            "",
            "## Data quality",
            "",
            f"Windows used: {used} of {total}.",
            f"Left out while the motor was on: {quality['excluded_vibration']}.",
            f"Left out for missing fields: {quality['excluded_missing']}.",
            f"Left out for an empty signal: {quality['excluded_low_quality']}.",
            "",
            DISCLAIMER,
        ]
    )
    return "\n".join(lines)


def session_numbers(summary: dict | None) -> dict[str, float | None]:
    """Read the fields a result card shows."""
    summary = summary or {}
    return {
        "log_amp": session_log_amp(summary),
        "peak_hz": session_peak_hz(summary),
        "tremor_pct": _float(summary.get("tremor_pct")),
        "taps_per_s": _float(summary.get("taps_per_s")),
        "tap_decrement": _float(summary.get("tap_decrement")),
        "tap_interval_cv": _float(summary.get("tap_interval_cv")),
        "intention_ratio": _float(summary.get("intention_ratio")),
        "cadence_spm": _float(summary.get("cadence_spm")),
        "stride_cv": _float(summary.get("stride_cv")),
        "asymmetry_pct": _float(summary.get("asymmetry_pct")),
    }


def _float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)  # type: ignore[arg-type]
