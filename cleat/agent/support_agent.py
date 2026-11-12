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
from cleat.settings import AGENT_RUNS_PER_DAY, AGENT_RUNS_PER_HOUR
from cleat.store import db

MAX_STEPS = 8
FALLBACK_REPLY = (
    "Thank you for your message. A member of our team will look into this and reply to you shortly.\n\n"
    f"{STORE_NAME} Support"
)


class RateLimited(Exception):
    """The hosted demo's hourly or daily agent-run limit has been reached."""


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

    Raises RateLimited when AGENT_RUNS_PER_HOUR runs have started in the last hour, or
    AGENT_RUNS_PER_DAY in the last 24 hours.
    """
    check_run_limits()
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


def check_run_limits() -> None:
    """Raise RateLimited, with a message a visitor can act on, if a demo run limit is reached."""
    if db.runs_in_last(hours=24) >= AGENT_RUNS_PER_DAY:
        raise RateLimited(
            f"Demo limit reached: this hosted demo allows {AGENT_RUNS_PER_DAY} agent runs a day, to stay within "
            "its free AI quota. Earlier runs are still on the Overview, Audit Log and Approvals pages. "
            "Please come back tomorrow, or run Cleat locally with your own keys (see the README)."
        )
    if db.runs_in_last_hour() >= AGENT_RUNS_PER_HOUR:
        raise RateLimited(
            f"Demo limit reached: this hosted demo allows {AGENT_RUNS_PER_HOUR} agent runs an hour. "
            "Earlier runs are still on the Overview, Audit Log and Approvals pages. Please try again in a little while."
        )


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
    # Text the agent may legitimately take an order ID from: this email and PayPal's replies in this run.
    seen = [message]
    for turns in range(1, MAX_STEPS + 1):
        response = model.invoke(messages)
        messages.append(response)
        if not response.tool_calls:
            reply = reply_text(response)
            break
        for call in response.tool_calls:
            content = unknown_order_error(call, seen) or _call_tool(firewall, guarded, call)
            seen.append(content)
            messages.append(ToolMessage(content=content, tool_call_id=call["id"]))
    return AgentResult(
        session_id=session_id,
        reply=reply or FALLBACK_REPLY,
        injection=verdict,
        steps=firewall.steps,
        model_turns=turns,
    )


def reply_text(message: BaseMessage) -> str:
    """Return a chat message's text, stripped.

    `.text` is a property in langchain-core 1.x but a method in 0.3, so both are handled.
    The 1.x value is a str that is also callable (calling it is deprecated), so check str first.
    """
    text = message.text
    if not isinstance(text, str) and callable(text):
        text = text()
    return str(text or "").strip()


def unknown_order_error(call: dict[str, Any], seen: Sequence[str]) -> str | None:
    """Return an error for a tool call whose order_id is not in the email or an earlier tool result.

    This stops the agent acting on an order ID it made up or carried over from somewhere else.
    The call never reaches the firewall or PayPal; the model gets the error and can correct itself.
    """
    order_id = str(call.get("args", {}).get("order_id") or "").strip()
    if not order_id or any(order_id.casefold() in text.casefold() for text in seen):
        return None
    return (
        f"Error: the tool call was rejected before reaching PayPal: order ID {order_id} does not appear in "
        "the customer's email. Use only order IDs the customer wrote."
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
