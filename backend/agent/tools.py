"""Care-planner tools. Each call is written to the agent timeline.

These tools describe stored sessions. They do not diagnose and they do not
suggest a dose.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from datetime import timedelta

from langchain_core.tools import tool
from sqlmodel import Session, col, select

from agent.report_text import DISCLAIMER, compose_report
from app.analytics import THRESHOLD_MAX, THRESHOLD_MIN, tremor_hours_by_day
from app.db import engine
from app.live import live_hub
from app.models import (
    AgentEvent,
    Baseline,
    CaptureSession,
    CareSettings,
    Command,
    Device,
    Medication,
    Report,
    SymptomLog,
)
from app.routes.analytics import _session_points, _symptom_points, persist_baselines
from app.schemas import as_utc, utcnow

logger = logging.getLogger(__name__)

RUN_ID: ContextVar[str] = ContextVar("tremorband_run_id", default="")
SLEEP_START_HOUR = 22
SLEEP_END_HOUR = 7
MAX_EXTRA_TESTS = 3
TEST_TYPES = ("rest", "postural", "finger_nose", "tapping", "gait")


def log_event(event_type: str, payload: dict) -> None:
    """Append one timeline row and broadcast it."""
    run_id = RUN_ID.get()
    if not run_id:
        return
    with Session(engine) as session:
        row = AgentEvent(run_id=run_id, ts=utcnow(), type=event_type, payload=payload)
        session.add(row)
        session.commit()
        session.refresh(row)
        event_id = row.id
    live_hub.publish(
        "agent",
        {"id": event_id, "run_id": run_id, "type": event_type, "payload": payload, "ts": utcnow().isoformat()},
    )
    logger.info("agent event run=%s type=%s", run_id, event_type)


def _in_sleep(now_hour: int, start: int = SLEEP_START_HOUR, end: int = SLEEP_END_HOUR) -> bool:
    if start == end:
        return False
    if start < end:
        return start <= now_hour < end
    return now_hour >= start or now_hour < end


def extra_tests_today(session: Session) -> int:
    """Agent-requested tests logged since midnight UTC."""
    start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    rows = session.exec(select(AgentEvent).where(AgentEvent.type == "trigger_test")).all()
    count = 0
    for row in rows:
        stamped = as_utc(row.ts)
        payload = row.payload or {}
        if stamped is not None and stamped >= start and payload.get("queued"):
            count += 1
    return count


def plan_extra_tests(session: Session) -> dict:
    """Say whether another guided test would fill a gap. It does not enqueue one."""
    now = utcnow()
    settings = session.get(CareSettings, 1)
    start_hour = settings.sleep_start_hour if settings is not None else SLEEP_START_HOUR
    end_hour = settings.sleep_end_hour if settings is not None else SLEEP_END_HOUR
    recent = [
        row.test_type
        for row in session.exec(select(CaptureSession))
        if as_utc(row.ts_start) is not None and as_utc(row.ts_start) >= now - timedelta(hours=6)
    ]
    missing = [name for name in TEST_TYPES if name not in recent]
    asleep = _in_sleep(now.hour, start_hour, end_hour)
    used = extra_tests_today(session)
    if asleep:
        decision = "inside the configured sleep hours, so no extra test is requested"
    elif used >= MAX_EXTRA_TESTS:
        decision = f"already requested {used} extra tests today, so no further test is requested"
    elif not missing:
        decision = "the recent hours already include each guided test, so no extra test is requested"
    else:
        decision = f"a {missing[0]} test would fill a gap in the recent hours"
    return {
        "sleep": asleep,
        "extra_tests_today": used,
        "max_extra_tests": MAX_EXTRA_TESTS,
        "missing": missing,
        "preferred_test": None if asleep or used >= MAX_EXTRA_TESTS or not missing else missing[0],
        "decision": decision,
    }


def _metrics(session: Session, test_type: str, days: int) -> list[dict]:
    start = utcnow() - timedelta(days=days)
    rows = []
    for point in _session_points(list(session.exec(select(CaptureSession)))):
        if point.ts < start:
            continue
        if test_type and point.test_type != test_type:
            continue
        rows.append(
            {
                "id": point.session_id,
                "test_type": point.test_type,
                "ts": point.ts.isoformat(),
                "log_amp": point.log_amp,
                "peak_hz": point.peak_hz,
                "is_synthetic": point.is_synthetic,
            }
        )
    return rows


@tool
def get_metrics(test_type: str = "", days: int = 14) -> dict:
    """Return recent session log amplitude and peak frequency. Not a diagnosis."""
    with Session(engine) as session:
        rows = _metrics(session, test_type.strip(), max(1, min(days, 90)))
    payload = {"test_type": test_type, "days": days, "n": len(rows), "sessions": rows[-40:]}
    log_event("tool", {"name": "get_metrics", "result_n": len(rows)})
    return payload


@tool
def get_passive_summary(days: int = 7) -> dict:
    """Return tremor-hours per day from passive summaries."""
    from app.models import PassiveSummary

    start = utcnow() - timedelta(days=max(1, min(days, 90)))
    with Session(engine) as session:
        rows = [
            (as_utc(row.ts), row.tremor_pct)
            for row in session.exec(select(PassiveSummary))
            if as_utc(row.ts) and as_utc(row.ts) >= start
        ]
    hours = tremor_hours_by_day([(ts, pct) for ts, pct in rows if ts is not None])
    payload = {"days": days, "tremor_hours": hours}
    log_event("tool", {"name": "get_passive_summary", "days": len(hours)})
    return payload


@tool
def get_medications(days: int = 14) -> dict:
    """Return doses the person already logged. This is not a dosing suggestion."""
    start = utcnow() - timedelta(days=max(1, min(days, 90)))
    with Session(engine) as session:
        rows = [
            {"ts": as_utc(row.ts).isoformat(), "name": row.name, "dose": row.dose}
            for row in session.exec(select(Medication).order_by(col(Medication.ts)))
            if as_utc(row.ts) and as_utc(row.ts) >= start
        ]
    log_event("tool", {"name": "get_medications", "n": len(rows)})
    return {"days": days, "medications": rows}


@tool
def get_symptoms(days: int = 14) -> dict:
    """Return symptom-log ratings and tags. A rating is not a diagnosis."""
    start = utcnow() - timedelta(days=max(1, min(days, 90)))
    with Session(engine) as session:
        points = _symptom_points(
            [
                row
                for row in session.exec(select(SymptomLog))
                if as_utc(row.ts) and as_utc(row.ts) >= start
            ]
        )
    payload = {
        "days": days,
        "symptoms": [
            {"ts": point.ts.isoformat(), "rating": point.rating, "tags": point.tags} for point in points
        ],
    }
    log_event("tool", {"name": "get_symptoms", "n": len(points)})
    return payload


@tool
def plan_tests() -> dict:
    """Decide whether another guided test would fill a gap. Does not start a test."""
    with Session(engine) as session:
        plan = plan_extra_tests(session)
    log_event("tool", {"name": "plan_tests", "decision": plan["decision"]})
    return plan


@tool
def trigger_test(test_type: str, reason: str) -> dict:
    """Ask the band to buzz and run one guided test. Refuses during sleep and after 3 extras today."""
    name = test_type.strip().replace("-", "_")
    if name == "finger_to_nose":
        name = "finger_nose"
    if name not in TEST_TYPES:
        result = {"queued": False, "reason": f"{test_type} is not a guided test"}
        log_event("trigger_test", result)
        return result
    with Session(engine) as session:
        plan = plan_extra_tests(session)
        if plan["sleep"] or plan["extra_tests_today"] >= MAX_EXTRA_TESTS:
            result = {"queued": False, "reason": plan["decision"], "test_type": name}
            log_event("trigger_test", result)
            return result
        device = session.exec(select(Device).order_by(col(Device.last_seen).desc())).first()
        if device is None:
            result = {"queued": False, "reason": "No band has checked in.", "test_type": name}
            log_event("trigger_test", result)
            return result
        session.add(
            Command(
                device_id=device.id,
                cmd="vibrate:ALERT",
                status="pending",
                created_by="agent",
                reason=reason[:200],
            )
        )
        session.add(
            Command(
                device_id=device.id,
                cmd=f"run_test:{name}",
                status="pending",
                created_by="agent",
                reason=reason[:200],
            )
        )
        session.commit()
        result = {
            "queued": True,
            "device_id": device.id,
            "test_type": name,
            "reason": reason[:200],
            "note": "The band was asked to buzz and run a test.",
        }
    log_event("trigger_test", result)
    return result


@tool
def wait_for_session(timeout_s: int = 30, test_type: str = "") -> dict:
    """Wait until a guided-test session finishes, then return its summary."""
    import time

    deadline = time.monotonic() + max(0, min(timeout_s, 90))
    name = test_type.strip().replace("-", "_")
    while True:
        with Session(engine) as session:
            rows = list(session.exec(select(CaptureSession).order_by(col(CaptureSession.id).desc())))
        for row in rows:
            if name and row.test_type not in {name, name.replace("_", "-")}:
                continue
            if row.ts_end is None and row.summary is None:
                continue
            payload = {
                "found": True,
                "id": row.id,
                "test_type": row.test_type,
                "summary": row.summary,
                "is_synthetic": row.is_synthetic,
            }
            log_event("tool", {"name": "wait_for_session", "found": True, "id": row.id})
            return payload
        if time.monotonic() >= deadline:
            payload = {"found": False, "test_type": name}
            log_event("tool", {"name": "wait_for_session", "found": False})
            return payload
        time.sleep(0.5)


@tool
def update_baseline(test_type: str, threshold_z: float, rationale: str) -> dict:
    """Move one comparison line after the person approves it. The line is not a diagnosis."""
    name = test_type.strip() or "rest"
    updated = min(THRESHOLD_MAX, max(THRESHOLD_MIN, float(threshold_z)))
    with Session(engine) as session:
        row = session.get(Baseline, name)
        if row is None:
            persist_baselines(session)
            session.commit()
            row = session.get(Baseline, name)
        if row is None:
            row = Baseline(
                test_type=name,
                mean_log_amp=0.0,
                sd_log_amp=0.0,
                mean_hz=0.0,
                threshold_z=updated,
                n_sessions=0,
                updated_at=utcnow(),
            )
        previous = row.threshold_z
        row.threshold_z = updated
        row.updated_at = utcnow()
        session.add(row)
        session.commit()
    payload = {
        "test_type": name,
        "old_threshold_z": previous,
        "threshold_z": updated,
        "rationale": rationale[:280],
    }
    logger.info("approved baseline change %s", payload)
    log_event("tool", {"name": "update_baseline", **payload})
    return payload


@tool
def draft_report(markdown: str = "") -> dict:
    """Store a clinician note built from the log. Model prose is not copied in."""
    del markdown
    with Session(engine) as session:
        body = compose_report(session)
        row = Report(created_at=utcnow(), markdown=body, status="draft", recipient="clinician")
        session.add(row)
        session.commit()
        session.refresh(row)
        report_id = row.id
    payload = {"id": report_id, "status": "draft", "disclaimer": DISCLAIMER}
    log_event("tool", {"name": "draft_report", "id": report_id})
    return payload


@tool
def send_report(report_id: int, recipient: str) -> dict:
    """Mark a draft as sent after the person approves sharing it."""
    with Session(engine) as session:
        row = session.get(Report, report_id)
        if row is None:
            payload = {"sent": False, "reason": f"report {report_id} was not found"}
            log_event("tool", {"name": "send_report", **payload})
            return payload
        row.status = "sent"
        row.recipient = recipient.strip() or row.recipient
        session.add(row)
        session.commit()
    payload = {"sent": True, "id": report_id, "recipient": recipient.strip(), "status": "sent"}
    logger.info("report sent id=%s recipient=%s", report_id, recipient)
    log_event("tool", {"name": "send_report", **payload})
    return payload


def collect_session_facts(limit: int | None = None) -> dict:
    """Stored session measurements. `limit` None keeps every session."""
    from app.capture import measurements

    with Session(engine) as session:
        rows = list(session.exec(select(CaptureSession).order_by(col(CaptureSession.id).desc())))
        chosen = rows if limit is None else rows[: max(1, min(int(limit), 40))]
        payload_rows = []
        for row in reversed(chosen):
            stats = measurements(session, row)
            payload_rows.append(
                {
                    "id": row.id,
                    "test_type": row.test_type,
                    "is_synthetic": row.is_synthetic,
                    "data_label": "simulated" if row.is_synthetic else "recorded",
                    "ts_start": as_utc(row.ts_start).isoformat() if as_utc(row.ts_start) else None,
                    "ts_end": as_utc(row.ts_end).isoformat() if as_utc(row.ts_end) else None,
                    **stats,
                }
            )
    return {"n_sessions": len(rows), "sessions": payload_rows}


@tool
def get_session_facts(limit: int = 12) -> dict:
    """Return stored session measurements. Synthetic sessions are marked simulated. Not a diagnosis."""
    payload = collect_session_facts(limit)
    log_event(
        "tool",
        {
            "name": "get_session_facts",
            "n_sessions": payload["n_sessions"],
            "shown": len(payload["sessions"]),
        },
    )
    return payload


READ_TOOLS = [get_metrics, get_passive_summary, get_medications, get_symptoms]
SCHEDULER_TOOLS = [get_metrics, get_passive_summary, plan_tests, trigger_test, wait_for_session]
WRITER_TOOLS = [get_metrics, get_passive_summary, get_medications, get_symptoms, draft_report]
MAIN_TOOLS = READ_TOOLS + [plan_tests, trigger_test, wait_for_session, update_baseline, draft_report, send_report]
ANALYSIS_TOOLS = [get_session_facts]
