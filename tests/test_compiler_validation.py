"""Tests that the policy compiler rejects rules outside the allowed fields and operators."""

import json

import pytest
from fakes import ScriptedLLM

from cleat.firewall.compiler import DEFAULT_POLICY_RULES, PolicyCompileError, compile_policy, seed_default_policy, simulate
from cleat.firewall.engine import decide
from cleat.firewall.schema import Rule
from cleat.store import db


def draft(*rules: dict) -> dict:
    return {"rules": list(rules)}


SMALL_REFUND = {
    "id": "R1",
    "description": "Refunds up to $50 on completed payments are fine.",
    "tools": ["refund_capture"],
    "conditions": [
        {"field": "amount", "op": "lte", "value": "50"},
        {"field": "capture_status", "op": "in", "value": "COMPLETED, PARTIALLY_REFUNDED"},
    ],
    "action": "allow",
}


def test_a_valid_draft_becomes_rules() -> None:
    [rule] = compile_policy("Refunds up to $50 on completed payments are fine.", ScriptedLLM(structured=[draft(SMALL_REFUND)]))
    assert rule.conditions[0].value == 50.0
    assert rule.conditions[1].value == ["COMPLETED", "PARTIALLY_REFUNDED"]


def test_an_unknown_field_is_rejected_and_retried_with_the_error() -> None:
    bad = {**SMALL_REFUND, "conditions": [{"field": "customer_lifetime_value", "op": "gt", "value": "500"}]}
    llm = ScriptedLLM(structured=[draft(bad), draft(SMALL_REFUND)])
    [rule] = compile_policy("policy", llm)
    assert rule.id == "R1"
    retry_prompt = llm.prompts[1][-1].content
    assert "customer_lifetime_value" in retry_prompt or "field" in retry_prompt


def test_still_invalid_after_one_retry_raises_with_the_errors() -> None:
    bad = {**SMALL_REFUND, "conditions": [{"field": "amount", "op": "approximately", "value": "50"}]}
    with pytest.raises(PolicyCompileError) as caught:
        compile_policy("policy", ScriptedLLM(structured=[draft(bad), draft(bad)]))
    assert "rule R1" in caught.value.errors[0]


@pytest.mark.parametrize(
    "change",
    [
        {"tools": ["accept_dispute_claim"]},
        {"tools": ["tier:everything"]},
        {"action": "maybe"},
        {"conditions": [{"field": "capture_status", "op": "gt", "value": "COMPLETED"}]},
        {"conditions": [{"field": "inbound_risk", "op": "eq", "value": "extreme"}]} | {"action": "block"},
    ],
)
def test_rules_outside_the_schema_are_rejected(change: dict) -> None:
    bad = {**SMALL_REFUND, **change}
    with pytest.raises(PolicyCompileError):
        compile_policy("policy", ScriptedLLM(structured=[draft(bad), draft(bad)]))


def test_an_empty_policy_and_duplicate_ids_are_rejected() -> None:
    with pytest.raises(PolicyCompileError, match="no rules"):
        compile_policy("policy", ScriptedLLM(structured=[draft(), draft()]))
    with pytest.raises(PolicyCompileError, match="unique"):
        compile_policy("policy", ScriptedLLM(structured=[draft(SMALL_REFUND, SMALL_REFUND)] * 2))


@pytest.mark.usefixtures("memory_db")
def test_simulate_shows_which_past_decisions_would_change() -> None:
    facts = {"tool": "refund_capture", "tier": "money", "inbound_risk": "low", "amount": 40.0,
             "capture_status": "COMPLETED", "remaining_refundable": 45.0}
    db.log_attempt(session_id="s", tool="refund_capture", tier="money", args_json="{}", decision="approve",
                   reason="Default for money actions.", facts_json=json.dumps(facts), amount=40.0, status="held")
    allow_small = Rule.model_validate(SMALL_REFUND | {"conditions": [{"field": "amount", "op": "lte", "value": 50}]})
    [row] = simulate([allow_small])
    assert (row["before"], row["after"], row["changed"]) == ("approve", "allow", True)


@pytest.mark.usefixtures("memory_db")
def test_the_bundled_default_policy_is_saved_once() -> None:
    seed_default_policy()
    seed_default_policy()
    assert len(db.policy_history()) == 1
    assert [rule.id for rule in db.active_rules()] == ["R1", "R2", "R3", "R4", "R5"]


def _refund(amount: float, captured: float, risk: str = "low") -> dict:
    return {"tool": "refund_capture", "tier": "money", "inbound_risk": risk, "amount": amount,
            "capture_status": "COMPLETED", "captured_amount": captured, "remaining_refundable": captured,
            "pct_of_capture": round(amount / captured * 100, 1), "window_total_24h": amount}


@pytest.mark.parametrize(
    ("scenario", "facts", "expected"),
    [
        ("03 $20 torn item", _refund(20, 22), ("allow", "R1")),
        ("04 $180 damaged saree", _refund(180, 240), ("approve", "R2")),
        ("05 injection, full refund", _refund(22, 22, risk="high"), ("block", "R4")),
        ("07 $300 on a $45 order", _refund(300, 45), ("block", "HARD-OVER-REFUND")),
    ],
)
def test_bundled_rules_decide_the_core_demo_scenarios(scenario: str, facts: dict, expected: tuple) -> None:
    rules = [Rule.model_validate(r) for r in json.loads(DEFAULT_POLICY_RULES.read_text(encoding="utf-8"))]
    decision = decide("refund_capture", "money", facts, rules)
    assert (decision.action, decision.rule_id) == expected, scenario
