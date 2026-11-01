"""Loads the demo email templates and fills their placeholders with real sandbox IDs
from the capture pool.
"""

import json
from dataclasses import dataclass
from typing import Any

from cleat.demo.pool import pick_capture
from cleat.settings import ROOT

EMAILS = ROOT / "data" / "emails"


class NoCaptureAvailable(Exception):
    """No seeded sandbox order has enough refundable balance left for this scenario."""


@dataclass(frozen=True)
class Scenario:
    """One demo email and the decision Cleat is expected to make on it."""

    id: str
    title: str
    template: str
    expected: str
    shows: str
    needs_order: bool = True
    min_remaining: float = 0.0
    exact_amount: float | None = None


@dataclass(frozen=True)
class FilledScenario:
    """A scenario email with real order details filled in."""

    scenario: Scenario
    message: str
    customer: str
    order: dict[str, Any] | None


def load_scenarios() -> list[Scenario]:
    """Return every scenario in data/emails/scenarios.json, in order."""
    return [Scenario(**entry) for entry in json.loads((EMAILS / "scenarios.json").read_text(encoding="utf-8"))]


def fill(scenario: Scenario) -> FilledScenario:
    """Fill the scenario's template from a suitable seeded order.

    Raises NoCaptureAvailable if the scenario needs an order and none has enough balance left.
    """
    order = pick_capture(scenario.min_remaining, scenario.exact_amount)
    if order is None and scenario.needs_order:
        raise NoCaptureAvailable(
            f"No seeded sandbox order has ${scenario.min_remaining:.2f} left to refund for scenario {scenario.id}."
        )
    customer = order["customer_name"] if order else "A customer"
    values = {
        "customer_name": customer,
        "order_id": order["order_id"] if order else "",
        "capture_id": order["capture_id"] if order else "",
        "amount": order["amount"] if order else "",
        "item": order["item"] if order else "",
    }
    message = (EMAILS / scenario.template).read_text(encoding="utf-8").format(**values)
    return FilledScenario(scenario=scenario, message=message, customer=customer, order=order)
