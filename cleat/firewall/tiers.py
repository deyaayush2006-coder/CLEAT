"""Maps every tool name to a risk tier: read, write, money, destructive or unknown.
Unknown tools are blocked (invariant I-3).

Names are the real ones from docs/toolkit_tools.txt. The installed toolkit (1.1.0) has no
dispute, invoice-payment or recurring-invoice tools, so none are listed here; if a future
toolkit adds them they arrive as "unknown" and are blocked until they are tiered.
"""

from typing import Literal

Tier = Literal["read", "write", "money", "destructive", "unknown"]
Action = Literal["allow", "approve", "block"]

TIERS: dict[str, Tier] = {
    # Read: look things up, change nothing.
    "get_order_details": "read",
    "list_products": "read",
    "show_product_details": "read",
    "list_subscription_plans": "read",
    "show_subscription_plan_details": "read",
    "show_subscription_details": "read",
    "list_invoices": "read",
    "get_invoice": "read",
    "generate_invoice_qr_code": "read",
    # Write: create or send something, but no money moves.
    "create_order": "write",
    "create_product": "write",
    "create_subscription_plan": "write",
    "create_subscription": "write",
    "create_invoice": "write",
    "send_invoice": "write",
    "send_invoice_reminder": "write",
    # Money: moves money between the store and a customer.
    "refund_capture": "money",
    "capture_order": "money",
    # Destructive: cancels something a customer relies on.
    "cancel_subscription": "destructive",
    "cancel_sent_invoice": "destructive",
}

DEFAULT_ACTION: dict[Tier, Action] = {
    "read": "allow",
    "write": "allow",
    "money": "approve",
    "destructive": "approve",
    "unknown": "block",
}


def tier_of(tool: str) -> Tier:
    """Return the tool's tier, or "unknown" for any name Cleat has not classified."""
    return TIERS.get(tool, "unknown")
