"""A scripted chat model for tests and the local demo.

It calls the care-planner tools in a fixed order. It does not invent a
diagnosis or a dose. Set TREMORBAND_MODEL to a provider:model string to use
a hosted model instead.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult


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


class ScriptedChatModel(BaseChatModel):
    """Return the next care-planner step from the messages already on the thread."""

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
        user = "\n".join(_text(message) for message in messages)
        done = _tool_names(messages)
        if "ROLE trend-analyst" in system:
            message = self._analyst(done)
        elif "ROLE assessment-scheduler" in system:
            message = self._scheduler(done, messages)
        elif "ROLE report-writer" in system:
            message = self._writer(done, messages)
        elif "move the comparison line" in user.lower():
            message = self._threshold(done)
        else:
            message = self._main(done, messages)
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _analyst(self, done: list[str]) -> AIMessage:
        if "get_metrics" not in done:
            return _call("get_metrics", {"test_type": "", "days": 14})
        if "get_symptoms" not in done:
            return _call("get_symptoms", {"days": 14})
        return AIMessage(
            content=(
                "Trend analyst: the numbers are in the tool results above. "
                "Compare them with the personal baseline. This is not a diagnosis. "
                "Discuss the pattern with the clinician."
            )
        )

    def _scheduler(self, done: list[str], messages: list[BaseMessage]) -> AIMessage:
        if "plan_tests" not in done:
            return _call("plan_tests", {})
        plan_text = _last_tool_text(messages, "plan_tests")
        preferred = ""
        try:
            preferred = str(json.loads(plan_text).get("preferred_test") or "")
        except json.JSONDecodeError:
            preferred = ""
        if preferred and "trigger_test" not in done:
            return _call(
                "trigger_test",
                {"test_type": preferred, "reason": "A recent hour has no session of this type."},
            )
        return AIMessage(
            content=(
                "Assessment scheduler: extra tests stay within the daily limit and outside sleep hours. "
                f"Plan: {plan_text[:500]}"
            )
        )

    def _writer(self, done: list[str], messages: list[BaseMessage]) -> AIMessage:
        if "draft_report" not in done:
            return _call("draft_report", {"markdown": ""})
        raw = _last_tool_text(messages, "draft_report")
        report_id = ""
        try:
            report_id = str(json.loads(raw).get("id"))
        except json.JSONDecodeError:
            report_id = ""
        return AIMessage(
            content=(
                f"Report writer: draft report id={report_id}. "
                "Monitoring aid, not a diagnosis. The note is ready for the person to approve."
            )
        )

    def _threshold(self, done: list[str]) -> AIMessage:
        if "update_baseline" not in done:
            return _call(
                "update_baseline",
                {
                    "test_type": "rest",
                    "threshold_z": 2.5,
                    "rationale": "The person asked to move the comparison line.",
                },
            )
        return AIMessage(content="The comparison line change has been handled. It is not a diagnosis.")

    def _main(self, done: list[str], messages: list[BaseMessage]) -> AIMessage:
        tasks = [name for name in done if name == "task"]
        if len(tasks) == 0:
            return _call(
                "task",
                {
                    "description": "Compare recent sessions with the personal baseline and return numbers.",
                    "subagent_type": "trend-analyst",
                },
            )
        if len(tasks) == 1:
            return _call(
                "task",
                {
                    "description": "Decide whether another guided test is useful. Stay inside sleep hours and the daily limit.",
                    "subagent_type": "assessment-scheduler",
                },
            )
        if len(tasks) == 2:
            return _call(
                "task",
                {
                    "description": "Draft the clinician note from the recorded numbers.",
                    "subagent_type": "report-writer",
                },
            )
        if "send_report" not in done:
            raw = _last_tool_text(messages, "task")
            report_id = 0
            marker = "draft report id="
            if marker in raw:
                token = raw.split(marker, 1)[1].split(".", 1)[0].strip()
                if token.isdigit():
                    report_id = int(token)
            return _call("send_report", {"report_id": report_id, "recipient": "clinician"})
        return AIMessage(
            content=(
                "Weekly review is ready. The numbers describe recorded sessions. "
                "Discuss them with the clinician. TremorBand is a monitoring aid, not a diagnostic device."
            )
        )
