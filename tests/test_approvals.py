"""Tests for approving held actions, including hash verification and expiry."""

import json
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from langchain_core.tools import StructuredTool

from cleat.firewall import approvals
from cleat.firewall.facts import CallContext
from cleat.firewall.interceptor import Firewall
from cleat.paypal.tools import RefundCaptureArgs
from cleat.store import db

pytestmark = pytest.mark.usefixtures("memory_db")


class RecordingRefundTool:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.tool = StructuredTool.from_function(
            func=self._run, name="refund_capture", description="Refund a capture.", args_schema=RefundCaptureArgs
        )

    def _run(self, **kwargs: Any) -> str:
        self.calls.append(kwargs)
        return json.dumps({"refund_id": "REF9", "status": "COMPLETED"})


def hold_refund(amount: float = 180) -> tuple[str, RecordingRefundTool]:
    """Hold a refund (no rules, so money defaults to approve) and return the approval ID."""
    raw = RecordingRefundTool()
    Firewall([], CallContext(session_id="s1")).guard(raw.tool).invoke({"capture_id": "CAP1", "amount": amount})
    newest, _ = db.pending_approvals()[0]
    return newest.id, raw


def test_approving_executes_exactly_the_frozen_request(fake_paypal: Callable[..., None]) -> None:
    fake_paypal(captured="250.00")
    approval_id, raw = hold_refund(180)
    result = approvals.approve(approval_id, note="Checked photos", tools={"refund_capture": raw.tool})
    assert result.status == "executed"
    assert [(c["capture_id"], c["amount"]) for c in raw.calls] == [("CAP1", 180.0)]
    attempt = db.get_attempt(result.attempt_id)
    assert (attempt.status, json.loads(attempt.result_json)["refund_id"]) == ("executed", "REF9")


def test_a_tampered_request_is_refused(fake_paypal: Callable[..., None]) -> None:
    fake_paypal(captured="250.00")
    approval_id, raw = hold_refund(180)
    db.update_approval(approval_id, args_json=json.dumps({"amount": 250, "capture_id": "CAP1"}))
    with pytest.raises(approvals.ApprovalError, match="modified"):
        approvals.approve(approval_id, tools={"refund_capture": raw.tool})
    assert raw.calls == [] and db.get_approval(approval_id).status == "failed"


def test_an_expired_approval_cannot_execute(fake_paypal: Callable[..., None]) -> None:
    fake_paypal(captured="250.00")
    approval_id, raw = hold_refund(180)
    db.update_approval(approval_id, created_at=db.utcnow() - timedelta(hours=25))
    with pytest.raises(approvals.ApprovalError, match="expired"):
        approvals.approve(approval_id, tools={"refund_capture": raw.tool})
    assert raw.calls == [] and db.get_approval(approval_id).status == "expired"


def test_hard_rules_run_again_before_executing(fake_paypal: Callable[..., None]) -> None:
    fake_paypal(captured="250.00")
    approval_id, raw = hold_refund(180)
    fake_paypal(captured="250.00", status="PARTIALLY_REFUNDED", refunds=["100.00"])  # refunded elsewhere meanwhile
    result = approvals.approve(approval_id, tools={"refund_capture": raw.tool})
    assert raw.calls == []
    assert result.status == "failed" and "more than the $150.00" in result.result_json


def test_denying_sends_nothing_to_paypal(fake_paypal: Callable[..., None]) -> None:
    fake_paypal(captured="250.00")
    approval_id, raw = hold_refund(180)
    result = approvals.deny(approval_id, note="Photos show no damage")
    assert (result.status, result.note, raw.calls) == ("denied", "Photos show no damage", [])
    assert db.get_attempt(result.attempt_id).status == "denied"


def test_a_decided_approval_cannot_be_approved_again(fake_paypal: Callable[..., None]) -> None:
    fake_paypal(captured="250.00")
    approval_id, raw = hold_refund(180)
    approvals.approve(approval_id, tools={"refund_capture": raw.tool})
    with pytest.raises(approvals.ApprovalError, match="already executed"):
        approvals.approve(approval_id, tools={"refund_capture": raw.tool})
    assert len(raw.calls) == 1


def test_expire_older_than_only_expires_stale_pending_approvals(fake_paypal: Callable[..., None]) -> None:
    fake_paypal(captured="250.00")
    stale_id, _ = hold_refund(180)
    db.update_approval(stale_id, created_at=db.utcnow() - timedelta(hours=30))
    fresh_id, _ = hold_refund(190)
    assert approvals.expire_older_than(24) == 1
    assert (db.get_approval(stale_id).status, db.get_approval(fresh_id).status) == ("expired", "pending")
