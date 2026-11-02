"""Deterministic policy engine that decides allow, approve or block for one attempted tool call.

Pure Python with no LLM involvement (invariant I-1). Hard rules are checked first (I-4)
and the most restrictive matching rule wins (I-7).
"""

from typing import Any

from cleat.firewall.schema import Decision, Rule
from cleat.firewall.tiers import DEFAULT_ACTION

SEVERITY = {"allow": 0, "approve": 1, "block": 2}
# From the capture_status enum in PayPal's Payments v2 OpenAPI spec. DECLINED, PENDING,
# REFUNDED and FAILED captures have nothing that can be refunded.
REFUNDABLE_STATUSES = frozenset({"COMPLETED", "PARTIALLY_REFUNDED"})
# From the subscription status enum in PayPal's Subscriptions v1 API: only these can be cancelled.
CANCELLABLE_STATUSES = frozenset({"ACTIVE", "SUSPENDED"})
# Half a cent, so float rounding never turns an exact full refund into an over-refund.
_TOLERANCE = 0.005


def hard_rules(tool: str, facts: dict[str, Any]) -> Decision | None:
    """Return a block that no policy can override, or None if no hard rule applies."""
    if "verification_error" in facts:
        return _block("HARD-UNVERIFIED", f"Could not verify this action with PayPal: {facts['verification_error']}", facts)
    if tool == "cancel_subscription":
        status = facts.get("subscription_status")
        if status not in CANCELLABLE_STATUSES:
            return _block(
                "HARD-NOT-CANCELLABLE",
                f"PayPal reports this subscription as {status}; only ACTIVE or SUSPENDED subscriptions can be cancelled.",
                facts,
            )
        return None
    if tool != "refund_capture":
        return None
    status = facts.get("capture_status")
    if status not in REFUNDABLE_STATUSES:
        return _block(
            "HARD-NOT-REFUNDABLE",
            f"PayPal reports this payment as {status}; only COMPLETED or PARTIALLY_REFUNDED payments can be refunded.",
            facts,
        )
    amount, remaining = facts.get("amount"), facts.get("remaining_refundable")
    if amount is None or remaining is None:
        return _block("HARD-UNVERIFIED", "The refund amount or refundable balance could not be verified.", facts)
    if amount > remaining + _TOLERANCE:
        return _block(
            "HARD-OVER-REFUND",
            f"Refund of ${amount:.2f} is more than the ${remaining:.2f} PayPal says is still refundable.",
            facts,
        )
    return None


def decide(tool: str, tier: str, facts: dict[str, Any], rules: list[Rule]) -> Decision:
    """Decide one tool call from verified facts and the active rules."""
    if hard := hard_rules(tool, facts):
        return hard
    if tier == "unknown":
        return _block("HARD-UNKNOWN", f"Unknown tool {tool!r} (fail closed).", facts)
    hits = [r for r in rules if r.applies_to(tool, tier) and all(c.holds(facts) for c in r.conditions)]
    if not hits:
        return Decision(action=DEFAULT_ACTION[tier], reason=f"Default for {tier} actions.", rule_id=None, facts=facts)
    # max() keeps the first of equally severe rules, so ties resolve in policy order.
    worst = max(hits, key=lambda rule: SEVERITY[rule.action])
    return Decision(action=worst.action, reason=worst.description, rule_id=worst.id, facts=facts)


def _block(rule_id: str, reason: str, facts: dict[str, Any]) -> Decision:
    return Decision(action="block", reason=reason, rule_id=rule_id, facts=facts)
