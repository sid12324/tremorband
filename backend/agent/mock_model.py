"""A scripted chat model for tests and the local demo.

It reads stored session numbers and writes a movement analysis. It does not
diagnose and it does not suggest medication. Set TREMORBAND_MODEL to a
provider:model string, or set OPENAI_API_KEY with TREMORBAND_MODEL unset, to
use a hosted model instead.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from agent.analysis_text import compose_analysis


def _text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                parts.append(str(block.get("text", "")))
        return "\n".join(parts)
    return str(content)


def _tool_names(messages: list[BaseMessage]) -> list[str]:
    return [message.name for message in messages if isinstance(message, ToolMessage) and message.name]


def _last_tool_text(messages: list[BaseMessage], name: str) -> str:
    found = ""
    for message in messages:
        if isinstance(message, ToolMessage) and message.name == name:
            found = _text(message)
    return found


def _call(name: str, args: dict[str, Any]) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": f"call-{uuid.uuid4().hex[:12]}", "type": "tool_call"}],
    )


def _facts(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {"n_sessions": 0, "sessions": []}
    if not isinstance(payload, dict):
        return {"n_sessions": 0, "sessions": []}
    return payload


class ScriptedChatModel(BaseChatModel):
    """Return the next analysis step from the messages already on the thread."""

    @property
    def _llm_type(self) -> str:
        return "tremorband-scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> ScriptedChatModel:
        """The script chooses the tool call, so binding is a no-op."""
        del tools, kwargs
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        del stop, run_manager, kwargs
        system = "\n".join(_text(message) for message in messages[:3])
        done = _tool_names(messages)
        if "ROLE session-reviewer" in system:
            message = self._reviewer(done, messages)
        elif "ROLE movement-analyst" in system:
            message = self._analyst(done, messages)
        else:
            message = self._main(done, messages)
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _reviewer(self, done: list[str], messages: list[BaseMessage]) -> AIMessage:
        if "get_session_facts" not in done:
            return _call("get_session_facts", {"limit": 12})
        facts = _facts(_last_tool_text(messages, "get_session_facts"))
        count = facts.get("n_sessions", 0)
        return AIMessage(
            content=(
                f"Session reviewer: stored sessions {count}. "
                "Synthetic rows are simulated. This is not a diagnosis."
            )
        )

    def _analyst(self, done: list[str], messages: list[BaseMessage]) -> AIMessage:
        if "get_session_facts" not in done:
            return _call("get_session_facts", {"limit": 12})
        return AIMessage(content=compose_analysis(_facts(_last_tool_text(messages, "get_session_facts"))))

    def _main(self, done: list[str], messages: list[BaseMessage]) -> AIMessage:
        tasks = [name for name in done if name == "task"]
        if len(tasks) == 0:
            return _call(
                "task",
                {
                    "description": "Read stored session numbers. Label simulated sessions.",
                    "subagent_type": "session-reviewer",
                },
            )
        if len(tasks) == 1:
            return _call(
                "task",
                {
                    "description": (
                        "Analyze the movement from the stored numbers. "
                        "Do not diagnose and do not suggest medication."
                    ),
                    "subagent_type": "movement-analyst",
                },
            )
        text = _last_tool_text(messages, "task")
        if "monitoring aid" not in text.lower():
            text = compose_analysis({"n_sessions": 0, "sessions": []})
        return AIMessage(content=text)
