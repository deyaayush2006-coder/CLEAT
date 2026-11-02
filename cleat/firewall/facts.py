"""Gathers the facts a decision is made on from PayPal and Cleat's own records,
never from numbers the agent asserts (invariant I-2).

For a refund, the capture's amount and status come from Payments v2 and its refund
history from the parent order in Orders v2, so refunds made outside Cleat still count.
For a cancellation, the subscription's status comes from Subscriptions v1.
"""

from dataclasses import dataclass
from typing import Any

import requests

from cleat.paypal import rest
from cleat.store import db

# PENDING refunds are already committed, so they reduce what is left to refund.
_COUNTED_REFUND_STATUSES = frozenset({"COMPLETED", "PENDING"})


@dataclass(frozen=True)
class CallContext:
    """What the firewall knows about the conversation a tool call came from."""

    session_id: str
    inbound_risk: str = "low"
    customer: str | None = None


def gather_facts(tool: str, tier: str, args: dict[str, Any], context: CallContext) -> dict[str, Any]:
    """Return the facts for one tool call.

    If PayPal cannot confirm a refund's details, the facts carry `verification_error`
    and the engine blocks the call instead of deciding on guesses.
    """
    facts: dict[str, Any] = {"tool": tool, "tier": tier, "inbound_risk": context.inbound_risk}
    if tool == "refund_capture":
        try:
            facts.update(_refund_facts(args))
        except (rest.PayPalError, requests.RequestException, KeyError, TypeError, ValueError) as e:
            facts["verification_error"] = str(e) or type(e).__name__
    elif tool == "cancel_subscription":
        try:
            facts.update(subscription_facts(str(args["subscription_id"])))
        except (rest.PayPalError, requests.RequestException, KeyError, TypeError, ValueError) as e:
            facts["verification_error"] = str(e) or type(e).__name__
    return facts


def subscription_facts(subscription_id: str) -> dict[str, Any]:
    """Return what PayPal says about a subscription now: its status and plan."""
    sub = rest.get_subscription(subscription_id)
    return {
        "subscription_id": subscription_id,
        "subscription_status": sub.data["status"],
        "plan_id": sub.data.get("plan_id"),
        "paypal_debug_id": sub.debug_id,
    }


def refund_position(capture_id: str) -> dict[str, Any]:
    """Return what PayPal says about a capture now: amount paid, status, refunds and what is left."""
    capture = rest.get_capture(capture_id)
    captured = round(float(capture.data["amount"]["value"]), 2)
    order_id = _parent_order_id(capture.data)
    refunded = _refunded_total(order_id, capture_id)
    return {
        "capture_id": capture_id,
        "order_id": order_id,
        "currency": capture.data["amount"]["currency_code"],
        "capture_status": capture.data["status"],
        "captured_amount": captured,
        "refunded_total": refunded,
        "remaining_refundable": round(captured - refunded, 2),
        "paypal_debug_id": capture.debug_id,
    }


def _refund_facts(args: dict[str, Any]) -> dict[str, Any]:
    amount = round(float(args["amount"]), 2)
    position = refund_position(str(args["capture_id"]))
    captured = position["captured_amount"]
    return {
        **position,
        "amount": amount,
        "pct_of_capture": round(amount / captured * 100, 1) if captured else None,
        "window_total_24h": round(db.refunded_last_24h() + amount, 2),
    }


def _parent_order_id(capture: dict[str, Any]) -> str:
    for link in capture.get("links", []):
        if link.get("rel") == "up" and "/checkout/orders/" in link.get("href", ""):
            return link["href"].rstrip("/").rsplit("/", 1)[-1]
    raise ValueError("PayPal did not link this capture to an order, so its refund history is unknown")


def _refunded_total(order_id: str, capture_id: str) -> float:
    order = rest.get_order(order_id).data
    total = 0.0
    for unit in order.get("purchase_units", []):
        for refund in unit.get("payments", {}).get("refunds", []):
            if refund.get("status") in _COUNTED_REFUND_STATUSES and _refunds_capture(refund, capture_id):
                total += float(refund["amount"]["value"])
    return round(total, 2)


def _refunds_capture(refund: dict[str, Any], capture_id: str) -> bool:
    up_links = [link.get("href", "") for link in refund.get("links", []) if link.get("rel") == "up"]
    # Without an "up" link the refund cannot be tied to another capture, so count it to stay conservative.
    return not up_links or any(href.rstrip("/").endswith(f"/captures/{capture_id}") for href in up_links)
