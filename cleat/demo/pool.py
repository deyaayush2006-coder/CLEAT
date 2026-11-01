"""Picks sandbox captures that still have enough refundable balance for a scenario,
so the hosted demo keeps working after many runs.

Cleat's own records only rank the candidates: they miss refunds made elsewhere and are
wiped by a demo reset. The chosen capture's real balance is confirmed with PayPal.
"""

import json
from typing import Any

import requests

from cleat.firewall.engine import REFUNDABLE_STATUSES
from cleat.firewall.facts import refund_position
from cleat.paypal.rest import PayPalError
from cleat.settings import ROOT
from cleat.store import db

FIXTURES = ROOT / "data" / "fixtures" / "orders.json"


def seeded_orders() -> list[dict[str, Any]]:
    """Return the orders recorded by scripts/seed_orders.py, or none if it has not been run."""
    return json.loads(FIXTURES.read_text(encoding="utf-8")) if FIXTURES.exists() else []


def pick_capture(min_remaining: float = 0.0, exact_amount: float | None = None) -> dict[str, Any] | None:
    """Return a seeded order whose capture can still refund `min_remaining`, or None.

    Candidates are tried tightest fit first, which keeps the large captures free for the
    scenarios that need them. Read-only scenarios (no minimum, no exact amount) skip the
    PayPal check because any real order will do.
    """
    refunded_here = db.refunded_by_capture()
    candidates = []
    for order in seeded_orders():
        paid = float(order["amount"])
        if exact_amount is not None and abs(paid - exact_amount) > 0.005:
            continue
        # An upper bound on the real balance, because PayPal may know of more refunds than Cleat does.
        estimate = round(paid - refunded_here.get(order["capture_id"], 0.0), 2)
        if estimate + 0.005 >= min_remaining:
            candidates.append((estimate, order))
    candidates.sort(key=lambda pair: pair[0])

    if min_remaining <= 0 and exact_amount is None:
        return candidates[0][1] if candidates else None
    for _, order in candidates:
        try:
            position = refund_position(order["capture_id"])
        except (PayPalError, requests.RequestException, KeyError, ValueError):
            continue
        if position["capture_status"] in REFUNDABLE_STATUSES and position["remaining_refundable"] + 0.005 >= max(min_remaining, 0.01):
            return order
    return None
