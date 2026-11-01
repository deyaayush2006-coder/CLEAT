"""The support agent: an explicit tool-calling loop over guarded tools, at most 8 steps,
returning the reply and a step-by-step trace.

The loop is written out rather than taken from a LangChain agent constructor, so every tool
call visibly passes through the firewall and the trace records exactly what happened.
"""

import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool

from cleat.agent.prompts import STORE_NAME, SUPPORT_AGENT
from cleat.firewall.facts import CallContext
from cleat.firewall.injection import InjectionVerdict, classify
from cleat.firewall.interceptor import Firewall
from cleat.settings import AGENT_RUNS_PER_HOUR
from cleat.store import db

MAX_STEPS = 8
FALLBACK_REPLY = (
    "Thank you for your message. A member of our team will look into this and reply to you shortly.\n\n"
    f"{STORE_NAME} Support"
)


class RateLimited(Exception):
    """The hosted demo's hourly agent-run limit has been reached."""


@dataclass
class AgentResult:
    """Everything one agent run produced, for the Inbox page."""

    session_id: str
    reply: str
    injection: InjectionVerdict
    steps: list[dict[str, Any]] = field(default_factory=list)
    model_turns: int = 0


def run_agent(
    message: str,
    llm: Any,
    tools: Sequence[BaseTool],
    customer: str | None = None,
) -> AgentResult:
    """Classify the message, then let the agent work on it through the firewall.

    Raises RateLimited when AGENT_RUNS_PER_HOUR runs have started in the last hour.
    """
    if db.runs_in_last_hour() >= AGENT_RUNS_PER_HOUR:
        raise RateLimited(f"The demo allows {AGENT_RUNS_PER_HOUR} agent runs per hour. Please try again later.")
    session_id = uuid.uuid4().hex[:12]
    db.start_run(session_id, message, customer)
    try:
        result = _run(session_id, message, llm, tools, customer)
    except Exception:
        db.finish_run(session_id, status="error")
        raise
    db.finish_run(
        session_id,
        status="done",
        injection_json=result.injection.model_dump_json(),
        trace_json=json.dumps(result.steps),
        reply=result.reply,
    )
    return result


def _run(session_id: str, message: str, llm: Any, tools: Sequence[BaseTool], customer: str | None) -> AgentResult:
    verdict = classify(message, llm)
    firewall = Firewall(db.active_rules(), CallContext(session_id=session_id, inbound_risk=verdict.risk, customer=customer))
    guarded = {tool.name: firewall.guard(tool) for tool in tools}
    model = llm.bind_tools(list(guarded.values()))
    messages: list[BaseMessage] = [
        SystemMessage(SUPPORT_AGENT),
        HumanMessage(f"Customer: {customer or 'unknown'}\n<email>\n{message}\n</email>"),
    ]
    reply = ""
    turns = 0
    for turns in range(1, MAX_STEPS + 1):
        response = model.invoke(messages)
        messages.append(response)
        if not response.tool_calls:
            reply = response.text.strip()
            break
        for call in response.tool_calls:
            messages.append(ToolMessage(content=_call_tool(firewall, guarded, call), tool_call_id=call["id"]))
    return AgentResult(
        session_id=session_id,
        reply=reply or FALLBACK_REPLY,
        injection=verdict,
        steps=firewall.steps,
        model_turns=turns,
    )


def _call_tool(firewall: Firewall, guarded: dict[str, BaseTool], call: dict[str, Any]) -> str:
    tool = guarded.get(call["name"])
    if tool is None:
        # The model asked for a tool it was never given; the firewall logs and blocks it (fail closed).
        return firewall.call(call["name"], call.get("args", {}), raw_tool=None)
    try:
        return str(tool.invoke(call.get("args", {})))
    except Exception as e:  # malformed arguments go back to the model instead of ending the run
        return f"Error: the tool call was rejected before reaching PayPal: {e}"
