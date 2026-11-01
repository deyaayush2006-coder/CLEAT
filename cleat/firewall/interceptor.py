"""Wraps raw tools so every call is checked by the firewall and logged, then run,
held for approval or blocked.
"""

import hashlib
import json
import uuid
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel

from cleat.firewall.engine import decide
from cleat.firewall.facts import CallContext, gather_facts
from cleat.firewall.schema import Decision, Rule
from cleat.firewall.tiers import tier_of
from cleat.store import db


def to_jsonable(value: Any) -> Any:
    """Convert tool arguments (which may hold pydantic models) into plain JSON values."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def canonical_json(args: dict[str, Any]) -> str:
    """Serialise arguments the same way every time, so their hash is stable."""
    return json.dumps(args, sort_keys=True, separators=(",", ":"))


def args_hash(canonical: str) -> str:
    """Return the SHA-256 of canonical arguments (invariant I-5)."""
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def run_raw(tool: BaseTool, args: dict[str, Any]) -> tuple[str, str]:
    """Run a raw tool and return (status, output), where status is executed or failed.

    PayPal tools return JSON on success and plain text on error, so non-JSON output is a failure.
    """
    try:
        output = str(tool.invoke(args))
    except Exception as e:  # a tool must never crash the agent run; the failure is logged instead
        return "failed", f"Error: {e}"
    try:
        json.loads(output)
    except ValueError:
        return "failed", output
    return "executed", output


class Firewall:
    """Checks, logs and executes tool calls for one agent run."""

    def __init__(self, rules: list[Rule], context: CallContext) -> None:
        self.rules = rules
        self.context = context
        self.steps: list[dict[str, Any]] = []

    def check(self, tool: str, args: dict[str, Any]) -> tuple[Decision, db.Attempt]:
        """Gather facts, decide and log one attempt; held attempts get a frozen approval."""
        tier = tier_of(tool)
        canonical = canonical_json(args)
        facts = gather_facts(tool, tier, args, self.context)
        decision = decide(tool, tier, facts, self.rules)
        attempt = db.log_attempt(
            session_id=self.context.session_id,
            customer=self.context.customer,
            tool=tool,
            tier=tier,
            args_json=canonical,
            decision=decision.action,
            reason=decision.reason,
            rule_id=decision.rule_id,
            facts_json=json.dumps(facts),
            amount=facts.get("amount"),
            status={"allow": "allowed", "approve": "held", "block": "blocked"}[decision.action],
        )
        if decision.action == "approve":
            approval = db.create_approval(
                id=uuid.uuid4().hex[:10],
                attempt_id=attempt.id,
                tool=tool,
                args_json=canonical,
                args_hash=args_hash(canonical),
            )
            attempt = db.update_attempt(attempt.id, approval_id=approval.id)
            decision = decision.model_copy(update={"approval_id": approval.id})
        return decision, attempt

    def call(self, name: str, args: dict[str, Any], raw_tool: BaseTool | None) -> str:
        """Run one tool call through the firewall and return what the agent should see."""
        clean = to_jsonable(args)
        decision, attempt = self.check(name, clean)
        step: dict[str, Any] = {
            "attempt_id": attempt.id,
            "tool": name,
            "tier": attempt.tier,
            "args": clean,
            "decision": decision.model_dump(mode="json"),
        }
        if decision.action == "allow" and raw_tool is not None:
            status, output = run_raw(raw_tool, clean)
            db.update_attempt(
                attempt.id,
                status=status,
                result_json=output,
                executed_at=db.utcnow() if status == "executed" else None,
            )
            step.update(status=status, result=output)
        elif decision.action == "approve":
            output = (
                f"HELD for human approval (id {decision.approval_id}): {decision.reason} "
                "Tell the customer a team member will review this."
            )
            step.update(status="held", result=output)
        else:
            output = f"BLOCKED by policy: {decision.reason} Do not retry or rephrase this action."
            step.update(status="blocked", result=output)
        self.steps.append(step)
        return output

    def guard(self, raw_tool: BaseTool) -> StructuredTool:
        """Return a tool with the raw tool's name and schema that runs through the firewall."""

        def guarded(**kwargs: Any) -> str:
            return self.call(raw_tool.name, kwargs, raw_tool)

        return StructuredTool.from_function(
            func=guarded,
            name=raw_tool.name,
            description=raw_tool.description,
            args_schema=raw_tool.args_schema,
        )
