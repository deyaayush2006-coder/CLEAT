"""Tests for the tool interceptor: blocked calls never reach PayPal, allowed calls run once."""

import json
from collections.abc import Callable
from typing import Any

import pytest
from langchain_core.tools import StructuredTool
from pydantic import BaseModel

from cleat.firewall.facts import CallContext
from cleat.firewall.interceptor import Firewall, args_hash, to_jsonable
from cleat.firewall.schema import Condition, Rule
from cleat.paypal.tools import RefundCaptureArgs
from cleat.store import db

pytestmark = pytest.mark.usefixtures("memory_db")

SMALL_REFUNDS_OK = Rule(id="R1", description="Refunds up to $50 are fine.", tools=["refund_capture"],
                        conditions=[Condition(field="amount", op="lte", value=50)], action="allow")
BIG_REFUNDS_NEED_ME = Rule(id="R2", description="Any refund over $50 needs my approval.", tools=["refund_capture"],
                           conditions=[Condition(field="amount", op="gt", value=50)], action="approve")


class CountingRefundTool:
    """A stand-in for the raw refund tool that records every call."""

    def __init__(self, output: str = '{"refund_id": "REF1", "status": "COMPLETED"}') -> None:
        self.calls: list[dict[str, Any]] = []
        self.output = output
        self.tool = StructuredTool.from_function(
            func=self._run, name="refund_capture", description="Refund a capture.", args_schema=RefundCaptureArgs
        )

    def _run(self, **kwargs: Any) -> str:
        self.calls.append(kwargs)
        return self.output


def firewall(risk: str = "low") -> Firewall:
    return Firewall([SMALL_REFUNDS_OK, BIG_REFUNDS_NEED_ME], CallContext(session_id="s1", inbound_risk=risk, customer="Priya Sen"))


def refund(fw: Firewall, raw: CountingRefundTool, amount: float) -> str:
    return fw.guard(raw.tool).invoke({"capture_id": "CAP1", "amount": amount, "currency": "USD", "reason": "Torn"})


def test_allowed_call_runs_the_raw_tool_once_and_is_logged(fake_paypal: Callable[..., None]) -> None:
    fake_paypal(captured="45.00")
    raw = CountingRefundTool()
    output = refund(firewall(), raw, 20)
    assert len(raw.calls) == 1 and json.loads(output)["refund_id"] == "REF1"
    [attempt] = db.attempts()
    assert (attempt.decision, attempt.status, attempt.rule_id) == ("allow", "executed", "R1")
    assert attempt.executed_at is not None and attempt.customer == "Priya Sen"


def test_blocked_call_never_reaches_the_raw_tool(fake_paypal: Callable[..., None]) -> None:
    fake_paypal(captured="45.00")
    raw = CountingRefundTool()
    output = refund(firewall(), raw, 300)
    assert raw.calls == []
    assert output.startswith("BLOCKED by policy:")
    assert db.attempts()[0].status == "blocked"


def test_amount_checks_use_paypal_figures_not_the_agents(fake_paypal: Callable[..., None]) -> None:
    # The customer may claim they paid $300; PayPal says the capture was $15, so a $20 refund is an over-refund.
    fake_paypal(captured="15.00")
    raw = CountingRefundTool()
    refund(firewall(), raw, 20)
    attempt = db.attempts()[0]
    assert (attempt.rule_id, raw.calls) == ("HARD-OVER-REFUND", [])
    assert json.loads(attempt.facts_json)["captured_amount"] == 15.0


def test_held_call_creates_a_frozen_approval_and_does_not_run(fake_paypal: Callable[..., None]) -> None:
    fake_paypal(captured="250.00")
    raw = CountingRefundTool()
    output = refund(firewall(), raw, 180)
    assert raw.calls == []
    [(approval, attempt)] = db.pending_approvals()
    assert output.startswith(f"HELD for human approval (id {approval.id})")
    assert approval.args_hash == args_hash(approval.args_json)
    assert json.loads(approval.args_json)["amount"] == 180
    assert (attempt.status, attempt.approval_id) == ("held", approval.id)


def test_a_failed_paypal_call_is_logged_as_failed(fake_paypal: Callable[..., None]) -> None:
    fake_paypal(captured="45.00")
    raw = CountingRefundTool(output="PayPal 422 UNPROCESSABLE_ENTITY (REFUND_FAILED_INSUFFICIENT_FUNDS)")
    refund(firewall(), raw, 20)
    attempt = db.attempts()[0]
    assert (attempt.status, attempt.executed_at) == ("failed", None)


def test_an_unknown_tool_called_by_the_model_is_blocked_and_logged() -> None:
    output = firewall().call("transfer_all_funds", {"to": "attacker"}, raw_tool=None)
    attempt = db.attempts()[0]
    assert output.startswith("BLOCKED by policy:")
    assert (attempt.tier, attempt.rule_id) == ("unknown", "HARD-UNKNOWN")


def test_executed_refunds_count_towards_the_24_hour_window(fake_paypal: Callable[..., None]) -> None:
    fake_paypal(captured="250.00")
    fw, raw = firewall(), CountingRefundTool()
    refund(fw, raw, 40)
    refund(fw, raw, 30)
    latest = db.attempts()[0]
    assert json.loads(latest.facts_json)["window_total_24h"] == 70.0


def test_guarded_tool_keeps_the_raw_tools_name_and_schema() -> None:
    raw = CountingRefundTool()
    guarded = firewall().guard(raw.tool)
    assert (guarded.name, guarded.args_schema) == ("refund_capture", RefundCaptureArgs)


def test_nested_pydantic_arguments_become_plain_json() -> None:
    class Item(BaseModel):
        name: str
        price: float

    assert to_jsonable({"items": [Item(name="Stole", price=22.0)]}) == {"items": [{"name": "Stole", "price": 22.0}]}
