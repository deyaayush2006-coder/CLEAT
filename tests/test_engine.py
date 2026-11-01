"""Tests for the deterministic policy engine."""

from typing import Any

import pytest
from pydantic import ValidationError

from cleat.firewall.engine import decide
from cleat.firewall.schema import Condition, Rule
from cleat.firewall.tiers import TIERS, tier_of


def refund_facts(amount: float = 20.0, captured: float = 45.0, refunded: float = 0.0, **extra: Any) -> dict[str, Any]:
    facts = {
        "tool": "refund_capture",
        "tier": "money",
        "inbound_risk": "low",
        "amount": amount,
        "captured_amount": captured,
        "remaining_refundable": round(captured - refunded, 2),
        "capture_status": "COMPLETED" if refunded == 0 else "PARTIALLY_REFUNDED",
        "pct_of_capture": round(amount / captured * 100, 1),
        "window_total_24h": amount,
    }
    facts.update(extra)
    return facts


def rule(rule_id: str, action: str, *conditions: tuple[str, str, Any], tools: tuple[str, ...] = ("refund_capture",)) -> Rule:
    return Rule(
        id=rule_id,
        description=f"Rule {rule_id}",
        tools=list(tools),
        conditions=[Condition(field=f, op=o, value=v) for f, o, v in conditions],
        action=action,
    )


SMALL_REFUNDS_OK = rule("R1", "allow", ("amount", "lte", 50))
BIG_REFUNDS_NEED_ME = rule("R2", "approve", ("amount", "gt", 50))
DAILY_CAP = rule("R3", "approve", ("window_total_24h", "gt", 300))
MANIPULATION_BLOCKS_MONEY = rule("R4", "block", ("inbound_risk", "in", ["medium", "high"]), tools=("tier:money",))
DEFAULT_POLICY = [SMALL_REFUNDS_OK, BIG_REFUNDS_NEED_ME, DAILY_CAP, MANIPULATION_BLOCKS_MONEY]


@pytest.mark.parametrize(("tool", "expected"), [("get_order_details", "allow"), ("create_invoice", "allow"),
                                                ("refund_capture", "approve"), ("cancel_subscription", "approve")])
def test_tier_defaults_apply_when_no_rule_matches(tool: str, expected: str) -> None:
    facts = refund_facts() if tool == "refund_capture" else {"tool": tool, "tier": tier_of(tool), "inbound_risk": "low"}
    decision = decide(tool, tier_of(tool), facts, [])
    assert decision.action == expected
    assert decision.rule_id is None


def test_unknown_tool_is_blocked_even_with_an_allow_rule() -> None:
    allow_all = Rule(id="A", description="Allow everything", tools=["tier:unknown"], action="allow")
    decision = decide("drain_wallet", "unknown", {"tool": "drain_wallet", "tier": "unknown"}, [allow_all])
    assert (decision.action, decision.rule_id) == ("block", "HARD-UNKNOWN")


def test_over_refund_is_blocked_even_when_a_rule_allows_it() -> None:
    allow_all = rule("A", "allow")
    decision = decide("refund_capture", "money", refund_facts(amount=300, captured=45), [allow_all])
    assert (decision.action, decision.rule_id) == ("block", "HARD-OVER-REFUND")


def test_previous_refunds_count_towards_the_over_refund_check() -> None:
    decision = decide("refund_capture", "money", refund_facts(amount=30, captured=45, refunded=20), [SMALL_REFUNDS_OK])
    assert decision.rule_id == "HARD-OVER-REFUND"


def test_refunding_exactly_the_remaining_balance_is_not_an_over_refund() -> None:
    decision = decide("refund_capture", "money", refund_facts(amount=25, captured=45, refunded=20), [SMALL_REFUNDS_OK])
    assert (decision.action, decision.rule_id) == ("allow", "R1")


@pytest.mark.parametrize("status", ["REFUNDED", "PENDING", "DECLINED", "FAILED", None])
def test_non_refundable_or_unknown_capture_status_is_blocked(status: str | None) -> None:
    decision = decide("refund_capture", "money", refund_facts(capture_status=status), [rule("A", "allow")])
    assert (decision.action, decision.rule_id) == ("block", "HARD-NOT-REFUNDABLE")


def test_facts_that_paypal_could_not_verify_block_the_call() -> None:
    facts = {"tool": "refund_capture", "tier": "money", "inbound_risk": "low", "verification_error": "404 RESOURCE_NOT_FOUND"}
    decision = decide("refund_capture", "money", facts, [rule("A", "allow")])
    assert (decision.action, decision.rule_id) == ("block", "HARD-UNVERIFIED")


@pytest.mark.parametrize(("amount", "expected", "rule_id"), [(20, "allow", "R1"), (50, "allow", "R1"),
                                                             (50.01, "approve", "R2"), (180, "approve", "R2")])
def test_small_refunds_are_allowed_and_large_ones_held(amount: float, expected: str, rule_id: str) -> None:
    decision = decide("refund_capture", "money", refund_facts(amount=amount, captured=250), DEFAULT_POLICY)
    assert (decision.action, decision.rule_id) == (expected, rule_id)


def test_high_injection_risk_blocks_money_despite_an_allow_rule() -> None:
    decision = decide("refund_capture", "money", refund_facts(amount=20, inbound_risk="high"), DEFAULT_POLICY)
    assert (decision.action, decision.rule_id) == ("block", "R4")


def test_injection_risk_does_not_block_reads() -> None:
    facts = {"tool": "get_order_details", "tier": "read", "inbound_risk": "high"}
    assert decide("get_order_details", "read", facts, DEFAULT_POLICY).action == "allow"


def test_daily_cap_holds_a_small_refund_that_crosses_it() -> None:
    decision = decide("refund_capture", "money", refund_facts(amount=45, captured=250, window_total_24h=335), DEFAULT_POLICY)
    assert (decision.action, decision.rule_id) == ("approve", "R3")


def test_most_restrictive_of_three_overlapping_rules_wins() -> None:
    rules = [rule("A", "allow"), rule("B", "approve"), rule("C", "block")]
    assert decide("refund_capture", "money", refund_facts(), rules).rule_id == "C"
    assert decide("refund_capture", "money", refund_facts(), rules[:2]).rule_id == "B"


def test_equally_severe_rules_resolve_in_policy_order() -> None:
    rules = [rule("FIRST", "approve"), rule("SECOND", "approve")]
    assert decide("refund_capture", "money", refund_facts(), rules).rule_id == "FIRST"


def test_a_missing_fact_never_matches_and_never_crashes() -> None:
    needs_pct = rule("P", "block", ("pct_of_capture", "gt", 10))
    facts = refund_facts()
    del facts["pct_of_capture"]
    decision = decide("refund_capture", "money", facts, [needs_pct])
    assert (decision.action, decision.rule_id) == ("approve", None)


def test_risk_levels_compare_by_severity() -> None:
    at_least_medium = Condition(field="inbound_risk", op="gte", value="medium")
    assert [at_least_medium.holds({"inbound_risk": r}) for r in ("low", "medium", "high")] == [False, True, True]


def test_string_comparisons_ignore_case() -> None:
    assert Condition(field="capture_status", op="eq", value="completed").holds({"capture_status": "COMPLETED"})
    assert Condition(field="capture_status", op="in", value=["Completed"]).holds({"capture_status": "COMPLETED"})


@pytest.mark.parametrize(
    "condition",
    [
        {"field": "customer_vip", "op": "eq", "value": "yes"},
        {"field": "amount", "op": "between", "value": 5},
        {"field": "amount", "op": "gt", "value": "fifty"},
        {"field": "capture_status", "op": "gt", "value": "COMPLETED"},
        {"field": "inbound_risk", "op": "gte", "value": "extreme"},
        {"field": "tool", "op": "in", "value": "refund_capture"},
        {"field": "capture_status", "op": "eq", "value": "COMPLETE"},
        {"field": "tier", "op": "eq", "value": "dangerous"},
        {"field": "tool", "op": "in", "value": ["refund_capture", "accept_dispute_claim"]},
    ],
)
def test_invalid_conditions_are_rejected(condition: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Condition.model_validate(condition)


def test_numeric_strings_are_accepted_for_numeric_fields() -> None:
    assert Condition(field="amount", op="gt", value="50").value == 50.0


@pytest.mark.parametrize("tools", [["accept_dispute_claim"], ["tier:everything"], []])
def test_rules_must_name_real_tools_or_tiers(tools: list[str]) -> None:
    with pytest.raises(ValidationError):
        Rule(id="X", description="x", tools=tools, action="block")


def test_every_registered_tool_has_a_tier(monkeypatch: pytest.MonkeyPatch) -> None:
    from cleat.paypal import tools

    monkeypatch.setenv("PAYPAL_CLIENT_ID", "test-client")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "test-secret")
    tools.raw_tools.cache_clear()
    try:
        names = {tool.name for tool in tools.raw_tools()}
    finally:
        tools.raw_tools.cache_clear()
    assert names == set(TIERS)
