"""Human approval of held actions. An approved action runs from its frozen stored
arguments only after their SHA-256 hash is verified (invariant I-5).

The agent never takes part in this: Cleat executes the stored request itself, so nothing
the agent says after the hold can change the amount or the capture.
"""

import json
from collections.abc import Mapping
from datetime import timedelta

from langchain_core.tools import BaseTool

from cleat.firewall.engine import hard_rules
from cleat.firewall.facts import CallContext, gather_facts
from cleat.firewall.interceptor import args_hash, run_raw
from cleat.firewall.tiers import tier_of
from cleat.store import db

APPROVAL_TTL = timedelta(hours=24)


class ApprovalError(Exception):
    """The approval cannot be acted on (missing, already decided, expired or tampered with)."""


def approve(approval_id: str, note: str = "", tools: Mapping[str, BaseTool] | None = None) -> db.Approval:
    """Verify, re-check and execute a held action. Returns the approval with its outcome.

    Hard rules run again on fresh PayPal facts, because the capture may have been refunded
    elsewhere while the action waited.
    """
    approval = _pending(approval_id)
    if approval.args_hash != args_hash(approval.args_json):
        _finish(approval, "failed", note, "Refused: the stored request no longer matches its hash.")
        raise ApprovalError("The stored request was modified after it was held; it was not executed.")

    attempt = db.get_attempt(approval.attempt_id)
    stored_facts = json.loads(attempt.facts_json) if attempt else {}
    context = CallContext(
        session_id=attempt.session_id if attempt else "approval",
        inbound_risk=stored_facts.get("inbound_risk", "low"),
        customer=attempt.customer if attempt else None,
    )
    args = json.loads(approval.args_json)
    blocked = hard_rules(approval.tool, gather_facts(approval.tool, tier_of(approval.tool), args, context))
    if blocked:
        return _finish(approval, "failed", note, f"Not executed: {blocked.reason}")

    if tools is None:
        from cleat.paypal.tools import raw_tools  # imported here so tests can run without PayPal credentials

        tools = {tool.name: tool for tool in raw_tools()}
    raw_tool = tools.get(approval.tool)
    if raw_tool is None:
        return _finish(approval, "failed", note, f"Not executed: no tool named {approval.tool!r}.")
    status, output = run_raw(raw_tool, args)
    return _finish(approval, status, note, output)


def deny(approval_id: str, note: str = "") -> db.Approval:
    """Reject a held action. Nothing is sent to PayPal."""
    return _finish(_pending(approval_id), "denied", note, None)


def expire_older_than(hours: float = APPROVAL_TTL.total_seconds() / 3600) -> int:
    """Expire pending approvals older than `hours` and return how many were expired."""
    cutoff = db.utcnow() - timedelta(hours=hours)
    expired = 0
    for approval, _ in db.pending_approvals():
        if approval.created_at < cutoff:
            _finish(approval, "expired", "", None)
            expired += 1
    return expired


def _pending(approval_id: str) -> db.Approval:
    approval = db.get_approval(approval_id)
    if approval is None:
        raise ApprovalError(f"No held action with id {approval_id}.")
    if approval.status != "pending":
        raise ApprovalError(f"This action was already {approval.status}.")
    if db.utcnow() - approval.created_at > APPROVAL_TTL:
        _finish(approval, "expired", "", None)
        raise ApprovalError("This action was held for more than 24 hours and has expired.")
    return approval


def _finish(approval: db.Approval, status: str, note: str, result: str | None) -> db.Approval:
    now = db.utcnow()
    updated = db.update_approval(approval.id, status=status, decided_at=now, note=note, result_json=result)
    db.update_attempt(
        approval.attempt_id,
        status=status,
        result_json=result,
        executed_at=now if status == "executed" else None,
    )
    return updated
