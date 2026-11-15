"""Movement-analysis graph.

The deep agent reviews stored sessions and writes an analysis from those
numbers. It does not diagnose and it does not suggest medication. The model
name comes from TREMORBAND_MODEL. When that variable is unset and
OPENAI_API_KEY is set, the model is openai:gpt-4o-mini. With no key, the
scripted model runs. The key itself is never logged.
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

from agent.analysis_text import compose_analysis, review_from_facts
from agent.mock_model import ScriptedChatModel
from agent.report_text import DISCLAIMER
from agent.tools import ANALYSIS_TOOLS, RUN_ID, collect_session_facts, log_event
from app.db import DATA_DIR

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = f"""ROLE movement-lead
You review stored TremorBand sessions and analyze the movement. {DISCLAIMER}
Delegate to the session reviewer, then to the movement analyst.
The review has three parts, in this order: the average across stored sessions, the session with the highest median log amplitude, and the most recent session.
Then write a short summary of those figures.
Add a care plan only when that highest median log amplitude is above the comparison line. Leave the care plan out otherwise.
Cite numbers from tool results. Label synthetic sessions as simulated.
Never diagnose. Never suggest medication.
Keep the monitoring-aid line in the analysis.
"""


def redact(text: str) -> str:
    """Remove the API key from text that might be logged."""
    secret = os.environ.get("OPENAI_API_KEY", "").strip()
    if secret:
        return text.replace(secret, "[redacted]")
    return text

_GRAPH = None
_SAVER: SqliteSaver | None = None
_CONN: sqlite3.Connection | None = None


def model_name() -> str:
    """Return the model string. The API key is not part of the result."""
    chosen = os.environ.get("TREMORBAND_MODEL")
    if chosen is not None and chosen.strip():
        return chosen.strip()
    if os.environ.get("OPENAI_API_KEY", "").strip():
        return "openai:gpt-4o-mini"
    return "mock"


def _build_model() -> Any:
    name = model_name()
    if name in {"", "mock"}:
        logger.info("movement analysis using the scripted model")
        return ScriptedChatModel()
    from langchain.chat_models import init_chat_model

    logger.info("movement analysis using model %s", name)
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
            "name": "session-reviewer",
            "description": "Read stored session numbers and say which sessions are simulated. Never diagnose.",
            "system_prompt": (
                "ROLE session-reviewer\n"
                "Call get_session_facts. Return the stored numbers. "
                "Label synthetic sessions as simulated. Never diagnose and never suggest medication. "
                f"{DISCLAIMER}"
            ),
            "tools": ANALYSIS_TOOLS,
            "interrupt_on": {},
        },
        {
            "name": "movement-analyst",
            "description": "Write a movement analysis that cites the stored session numbers. Never diagnose.",
            "system_prompt": (
                "ROLE movement-analyst\n"
                "Call get_session_facts. From those stored numbers, write three sections in order: "
                "the average across stored sessions, the session with the highest median log amplitude, "
                "and the most recent session. Then a short summary. "
                "Add a care plan only when that highest median log amplitude is above the comparison line. "
                "Leave the care plan out otherwise. "
                "Label synthetic sessions as simulated. Never diagnose and never suggest medication. "
                f"Include this line: {DISCLAIMER} Also include: Monitoring aid, not a diagnosis."
            ),
            "tools": ANALYSIS_TOOLS,
            "interrupt_on": {},
        },
    ]
    _GRAPH = create_deep_agent(
        model=model,
        tools=ANALYSIS_TOOLS,
        system_prompt=SYSTEM_PROMPT,
        subagents=subagents,
        interrupt_on={},
        checkpointer=_checkpointer(),
        name="movement-analysis",
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


def _published_analysis() -> tuple[str, dict[str, Any]]:
    """The page review, drafted from every stored session.

    The movement analyst writes this same review from the session facts.
    Rebuilding it here keeps the average across every stored session, and
    keeps the care plan out unless the highest median log amplitude is above
    the comparison line.
    """
    facts = collect_session_facts()
    review = review_from_facts(facts)
    return compose_analysis(facts), review


def run_thread(thread_id: str, prompt: str) -> dict[str, Any]:
    """Run until the graph finishes or pauses."""
    graph = build_graph()
    token = RUN_ID.set(thread_id)
    log_event("status", {"phase": "started"})
    try:
        for chunk in graph.stream(
            {"messages": [HumanMessage(content=redact(prompt))]},
            _config(thread_id),
            stream_mode="updates",
        ):
            log_event("step", _summarize_chunk(chunk))
        analysis, review = _published_analysis()
        log_event("analysis", {"text": analysis, "review": review})
        interrupts = _interrupt_payload(graph, thread_id)
        if interrupts:
            log_event("interrupt", {"interrupts": interrupts})
            return {"status": "interrupted", "interrupts": interrupts, "analysis": analysis, "review": review}
        log_event("status", {"phase": "finished"})
        return {"status": "finished", "interrupts": [], "analysis": analysis, "review": review}
    finally:
        RUN_ID.reset(token)


def resume_thread(thread_id: str, decisions: list[dict[str, Any]]) -> dict[str, Any]:
    """Continue a paused run. `decisions` is the batched HITL response."""
    graph = build_graph()
    token = RUN_ID.set(thread_id)
    log_event("resume", {"decisions": redact(str(decisions))[:500]})
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
