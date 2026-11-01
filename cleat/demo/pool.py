"""Picks sandbox captures that still have enough refundable balance for a scenario,
so the hosted demo keeps working after many runs.

Balances here are estimates from refunds made through Cleat. They only choose which order to
use; the firewall still fetches the real balance from PayPal before deciding anything.
"""

import json
from typing import Any

from cleat.settings import ROOT
from cleat.store import db

FIXTURES = ROOT / "data" / "fixtures" / "orders.json"


def seeded_orders() -> list[dict[str, Any]]:
    """Return the orders recorded by scripts/seed_orders.py, or none if it has not been run."""
    return json.loads(FIXTURES.read_text(encoding="utf-8")) if FIXTURES.exists() else []


def pick_capture(min_remaining: float = 0.0, exact_amount: float | None = None) -> dict[str, Any] | None:
    """Return the seeded order with the smallest estimated balance that still covers `min_remaining`.

    Choosing the tightest fit keeps the large captures free for the scenarios that need them.
    """
    refunded = db.refunded_by_capture()
    best: dict[str, Any] | None = None
    best_left = 0.0
    for order in seeded_orders():
        if order.get("capture_status") != "COMPLETED":
            continue
        paid = float(order["amount"])
        if exact_amount is not None and abs(paid - exact_amount) > 0.005:
            continue
        left = round(paid - refunded.get(order["capture_id"], 0.0), 2)
        if left + 0.005 < min_remaining:
            continue
        if best is None or left < best_left:
            best, best_left = order, left
    return best
