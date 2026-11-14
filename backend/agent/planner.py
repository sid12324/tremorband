"""Care planner graph.

`create_deep_agent` pauses before `send_report` and `update_baseline`. The
resume payload for the installed deepagents 0.7.38 / langchain batched
interrupt is `{"decisions": [{"type": "approve"|"edit"|"reject", ...}]}`.
An edit replaces the action:

    {"type": "edit", "edited_action": {"name": "send_report", "args": {...}}}

Subagents do not receive those two tools. Sharing and threshold changes stay
on the main agent, where the approval interrupt is resumed.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from agent.mock_model import ScriptedChatModel
from agent.report_text import DISCLAIMER
from agent.tools import (
    MAIN_TOOLS,
    READ_TOOLS,
    RUN_ID,
    SCHEDULER_TOOLS,
    WRITER_TOOLS,
    log_event,
)
from app.db import DATA_DIR

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = f"""ROLE care-planner
You are the TremorBand care planner. {DISCLAIMER}
Plan with the to-do tool, then delegate. The trend-analyst compares sessions with the personal baseline. The assessment-scheduler decides whether another guided test is useful. The report-writer drafts the clinician note.
Cite numbers from tool results. Label synthetic sessions as simulated.
Never give medication advice and never diagnose. Recommend discussing the findings with the clinician.
Only you may call send_report or update_baseline. Wait for the person's approval. Do not ask a subagent to share a note or move a comparison line.
"""

_GRAPH = None
_SAVER: SqliteSaver | None = None
_CONN: sqlite3.Connection | None = None


def model_name() -> str:
    """Return the configured model string. `mock` uses the scripted local model."""
    return os.environ.get("TREMORBAND_MODEL", "mock")


def _build_model() -> Any:
    name = model_name()
    if name in {"", "mock"}:
        logger.info("care planner using the scripted model")
        return ScriptedChatModel()
    from langchain.chat_models import init_chat_model

    logger.info("care planner using model %s", name)
    return init_chat_model(name)


def _checkpointer() -> SqliteSaver:
    global _SAVER, _CONN
    if _SAVER is None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        path = Path(os.environ.get("TREMORBAND_CHECKPOINT", DATA_DIR / "agent.db"))
        _CONN = sqlite3.connect(str(path), check_same_thread=False)
        _SAVER = SqliteSaver(_CONN)
        _SAVER.setup()
    return _SAVER


def build_graph() -> Any:
    """Create the deep agent once and keep the SQLite checkpointer open."""
    global _GRAPH
    if _GRAPH is not None:
        return _GRAPH
    from deepagents import create_deep_agent

    model = _build_model()
    subagents = [
        {
            "name": "trend-analyst",
            "description": "Compare recent sessions with the personal baseline and return numeric findings with confidence. Never diagnose.",
            "system_prompt": (
                "ROLE trend-analyst\n"
                "Return numeric findings from the tools. Never diagnose and never suggest a dose. "
                f"{DISCLAIMER}"
            ),
            "tools": READ_TOOLS,
            "interrupt_on": {},
        },
        {
            "name": "assessment-scheduler",
            "description": "Decide whether another guided test is useful. At most 3 extra tests a day, never during sleep hours, prefer missing test types.",
            "system_prompt": (
                "ROLE assessment-scheduler\n"
                "Call plan_tests before trigger_test. Never diagnose and never suggest a dose. "
                f"{DISCLAIMER}"
            ),
            "tools": SCHEDULER_TOOLS,
            "interrupt_on": {},
        },
        {
            "name": "report-writer",
            "description": "Draft a one-page clinician note from recorded numbers, including the monitoring-aid line.",
            "system_prompt": (
                "ROLE report-writer\n"
                "Call draft_report. Do not call send_report. Never diagnose and never suggest a dose. "
                f"{DISCLAIMER}"
            ),
            "tools": WRITER_TOOLS,
            "interrupt_on": {},
        },
    ]
    _GRAPH = create_deep_agent(
        model=model,
        tools=MAIN_TOOLS,
        system_prompt=SYSTEM_PROMPT,
        subagents=subagents,
        interrupt_on={
            "send_report": {"allowed_decisions": ["approve", "edit", "reject"]},
            "update_baseline": {"allowed_decisions": ["approve", "reject"]},
        },
        checkpointer=_checkpointer(),
        name="care-planner",
    )
    return _GRAPH


def _config(thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}}


def _interrupt_payload(graph: Any, thread_id: str) -> list[dict[str, Any]]:
    state = graph.get_state(_config(thread_id))
    payload = []
    for item in state.interrupts:
        value = item.value
        payload.append({"id": item.id, "value": value})
    return payload


def run_thread(thread_id: str, prompt: str) -> dict[str, Any]:
    """Run until the graph pauses for approval or finishes."""
    graph = build_graph()
    token = RUN_ID.set(thread_id)
    log_event("status", {"phase": "started", "prompt": prompt[:280]})
    try:
        for chunk in graph.stream(
            {"messages": [HumanMessage(content=prompt)]},
            _config(thread_id),
            stream_mode="updates",
        ):
            log_event("step", _summarize_chunk(chunk))
        interrupts = _interrupt_payload(graph, thread_id)
        if interrupts:
            log_event("interrupt", {"interrupts": interrupts})
            return {"status": "interrupted", "interrupts": interrupts}
        log_event("status", {"phase": "finished"})
        return {"status": "finished", "interrupts": []}
    finally:
        RUN_ID.reset(token)


def resume_thread(thread_id: str, decisions: list[dict[str, Any]]) -> dict[str, Any]:
    """Continue a paused run. `decisions` is the batched HITL response."""
    graph = build_graph()
    token = RUN_ID.set(thread_id)
    log_event("resume", {"decisions": decisions})
    try:
        for chunk in graph.stream(
            Command(resume={"decisions": decisions}),
            _config(thread_id),
            stream_mode="updates",
        ):
            log_event("step", _summarize_chunk(chunk))
        interrupts = _interrupt_payload(graph, thread_id)
        if interrupts:
            log_event("interrupt", {"interrupts": interrupts})
            return {"status": "interrupted", "interrupts": interrupts}
        log_event("status", {"phase": "finished"})
        return {"status": "finished", "interrupts": []}
    finally:
        RUN_ID.reset(token)


def _summarize_chunk(chunk: Any) -> dict[str, Any]:
    """Keep a short, JSON-safe description of one stream update."""
    if not isinstance(chunk, dict):
        return {"text": str(chunk)[:300]}
    summary: dict[str, Any] = {"nodes": list(chunk.keys())}
    for node, update in chunk.items():
        if not isinstance(update, dict):
            continue
        messages = update.get("messages") or []
        names = []
        for message in messages:
            tool_calls = getattr(message, "tool_calls", None) or []
            for call in tool_calls:
                names.append(call.get("name"))
            name = getattr(message, "name", None)
            if name:
                names.append(name)
        if names:
            summary[str(node)] = names
    return summary
