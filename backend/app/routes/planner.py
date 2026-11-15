"""Care planner runs, approval resume, and clinician notes."""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel import Session, col, select

from app.db import get_session
from app.models import AgentEvent, Report
from app.schemas import as_utc, utcnow

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["planner"])


class RunIn(BaseModel):
    """Start a care-planner thread."""

    prompt: str = Field(
        default="Review the stored sessions and analyze the movement.",
        max_length=2000,
    )


class DecisionIn(BaseModel):
    """One batched approval decision."""

    type: str
    message: str | None = None
    edited_action: dict | None = None


class ResumeIn(BaseModel):
    """Continue a paused thread with the installed deepagents decision list."""

    thread_id: str
    decisions: list[DecisionIn]


class ReportRead(BaseModel):
    """A stored clinician note."""

    id: int
    created_at: str
    markdown: str
    status: str
    recipient: str | None


def _event_read(row: AgentEvent) -> dict:
    return {
        "id": row.id,
        "run_id": row.run_id,
        "ts": as_utc(row.ts).isoformat() if as_utc(row.ts) else None,
        "type": row.type,
        "payload": row.payload,
    }


def _run_view(session: Session, run_id: str) -> dict:
    rows = list(
        session.exec(select(AgentEvent).where(AgentEvent.run_id == run_id).order_by(col(AgentEvent.id)))
    )
    if not rows:
        raise HTTPException(status_code=404, detail=f"run {run_id} not found")
    status = "running"
    interrupts: list = []
    for row in rows:
        payload = row.payload or {}
        if row.type == "status" and payload.get("phase") in {"finished", "error"}:
            status = "error" if payload.get("phase") == "error" else "finished"
            interrupts = []
        elif row.type == "interrupt":
            status = "interrupted"
            interrupts = payload.get("interrupts") or []
    return {"id": run_id, "thread_id": run_id, "status": status, "events": [_event_read(row) for row in rows], "interrupts": interrupts}


def _safe_call(target, thread_id: str, payload) -> None:
    from agent.planner import resume_thread, run_thread
    from agent.tools import RUN_ID, log_event

    try:
        if target == "run":
            run_thread(thread_id, payload)
        else:
            resume_thread(thread_id, payload)
    except Exception as exc:
        from agent.planner import redact

        logger.error("movement analysis run %s failed: %s", thread_id, redact(str(exc))[:400])
        token = RUN_ID.set(thread_id)
        try:
            log_event("status", {"phase": "error", "message": redact(str(exc))[:400]})
        finally:
            RUN_ID.reset(token)


@router.post("/agent/run")
def start_run(body: RunIn) -> dict[str, str]:
    """Start a weekly review or a chat turn. Events stream on the run id."""
    run_id = str(uuid.uuid4())
    threading.Thread(target=_safe_call, args=("run", run_id, body.prompt), name=f"planner-{run_id[:8]}", daemon=True).start()
    logger.info("movement analysis started %s", run_id)
    return {"id": run_id, "thread_id": run_id, "status": "started"}


@router.post("/agent/resume")
def resume_run(body: ResumeIn, session: Session = Depends(get_session)) -> dict[str, str]:
    """Apply approve, edit, or reject and continue the same thread."""
    decisions = []
    for decision in body.decisions:
        item: dict = {"type": decision.type}
        if decision.message:
            item["message"] = decision.message
        if decision.edited_action:
            item["edited_action"] = decision.edited_action
        decisions.append(item)
        if decision.type == "reject":
            _reject_open_report(session, body.thread_id, decision.message or "")
    threading.Thread(
        target=_safe_call,
        args=("resume", body.thread_id, decisions),
        name=f"resume-{body.thread_id[:8]}",
        daemon=True,
    ).start()
    return {"thread_id": body.thread_id, "status": "resuming"}


def _reject_open_report(session: Session, run_id: str, message: str) -> None:
    rows = list(session.exec(select(AgentEvent).where(AgentEvent.run_id == run_id).order_by(col(AgentEvent.id))))
    report_id = None
    for row in rows:
        if row.type != "interrupt":
            continue
        for interrupt in (row.payload or {}).get("interrupts") or []:
            for action in (interrupt.get("value") or {}).get("action_requests") or []:
                if action.get("name") == "send_report":
                    report_id = (action.get("args") or {}).get("report_id")
    if report_id is None:
        return
    report = session.get(Report, int(report_id))
    if report is None or report.status != "draft":
        return
    report.status = "rejected"
    session.add(report)
    session.commit()
    logger.info("report %s rejected: %s", report_id, message[:160])


@router.get("/agent/runs")
def list_runs(session: Session = Depends(get_session)) -> list[dict[str, str]]:
    """Recent run ids, newest first."""
    rows = session.exec(select(AgentEvent).order_by(col(AgentEvent.id).desc())).all()
    seen: list[str] = []
    for row in rows:
        if row.run_id not in seen:
            seen.append(row.run_id)
        if len(seen) >= 20:
            break
    return [{"id": run_id, "thread_id": run_id} for run_id in seen]


@router.get("/agent/runs/{run_id}")
def get_run(run_id: str, session: Session = Depends(get_session)) -> dict:
    """Timeline, status, and any approval interrupt for one run."""
    return _run_view(session, run_id)


@router.get("/agent/runs/{run_id}/stream")
def stream_run(run_id: str) -> StreamingResponse:
    """Server-sent events for a run, including events already stored."""

    def generate() -> Iterator[str]:
        seen = 0
        idle = 0
        while idle < 40:
            with engine_session() as session:
                try:
                    view = _run_view(session, run_id)
                except HTTPException:
                    view = None
            if view is None:
                time.sleep(0.25)
                idle += 1
                continue
            events = view["events"]
            for event in events[seen:]:
                yield f"data: {json.dumps(event)}\n\n"
            seen = len(events)
            if view["status"] in {"finished", "error", "interrupted"} and seen:
                yield f"data: {json.dumps({'type': 'status', 'payload': {'phase': view['status'], 'interrupts': view['interrupts']}})}\n\n"
                return
            time.sleep(0.3)
            idle += 1

    return StreamingResponse(generate(), media_type="text/event-stream")


def engine_session() -> Session:
    from app.db import engine

    return Session(engine)


@router.get("/reports", response_model=list[ReportRead])
def list_reports(session: Session = Depends(get_session)) -> list[ReportRead]:
    """Clinician notes, newest first."""
    rows = session.exec(select(Report).order_by(col(Report.id).desc())).all()
    return [_report_read(row) for row in rows]


@router.get("/reports/{report_id}", response_model=ReportRead)
def get_report(report_id: int, session: Session = Depends(get_session)) -> ReportRead:
    """One clinician note."""
    row = session.get(Report, report_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"report {report_id} not found")
    return _report_read(row)


@router.get("/reports/{report_id}/pdf")
def report_pdf(report_id: int, session: Session = Depends(get_session)) -> Response:
    """Download the note as a PDF. The monitoring-aid line is on the page."""
    from app.pdf_note import note_pdf

    row = session.get(Report, report_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"report {report_id} not found")
    return Response(
        content=note_pdf(row.markdown),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="tremorband-note-{report_id}.pdf"'},
    )


def _report_read(row: Report) -> ReportRead:
    if row.id is None:
        raise HTTPException(status_code=500, detail="report id was not assigned")
    stamped = as_utc(row.created_at) or utcnow()
    return ReportRead(
        id=row.id,
        created_at=stamped.isoformat(),
        markdown=row.markdown,
        status=row.status,
        recipient=row.recipient,
    )
