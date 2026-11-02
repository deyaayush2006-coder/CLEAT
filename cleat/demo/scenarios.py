"""Loads the demo email templates and fills their placeholders with real sandbox IDs
from the capture and subscription pools.
"""

import json
from dataclasses import dataclass
from typing import Any

from cleat.demo import pool
from cleat.settings import ROOT

EMAILS = ROOT / "data" / "emails"


class ScenarioUnavailable(Exception):
    """No seeded sandbox order or subscription is left that this scenario can use."""


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
    needs_subscription: bool = False


@dataclass(frozen=True)
class FilledScenario:
    """A scenario email with real order details filled in."""

    scenario: Scenario
    message: str
    customer: str
    order: dict[str, Any] | None
    subscription: dict[str, Any] | None = None


def load_scenarios() -> list[Scenario]:
    """Return every scenario in data/emails/scenarios.json, in order."""
    return [Scenario(**entry) for entry in json.loads((EMAILS / "scenarios.json").read_text(encoding="utf-8"))]


def fill(scenario: Scenario) -> FilledScenario:
    """Fill the scenario's template from a suitable seeded order and, if needed, subscription.

    Raises ScenarioUnavailable if the scenario needs an order or subscription and none is left.
    """
    subscription = _pick_subscription() if scenario.needs_subscription else None
    order = None if scenario.needs_subscription else pool.pick_capture(scenario.min_remaining, scenario.exact_amount)
    if order is None and scenario.needs_order:
        if not pool.seeded_orders():
            raise ScenarioUnavailable("No sandbox orders have been seeded yet.")
        if scenario.exact_amount is not None:
            raise ScenarioUnavailable(f"No seeded ${scenario.exact_amount:.2f} order is still refundable.")
        raise ScenarioUnavailable(f"No seeded sandbox order still has ${scenario.min_remaining:.2f} left to refund.")
    if subscription:
        customer = subscription["customer_name"]
    else:
        customer = order["customer_name"] if order else "A customer"
    values = {
        "subscription_id": subscription["subscription_id"] if subscription else "",
        "customer_name": customer,
        "order_id": order["order_id"] if order else "",
        "capture_id": order["capture_id"] if order else "",
        "amount": order["amount"] if order else "",
        "item": order["item"] if order else "",
    }
    message = (EMAILS / scenario.template).read_text(encoding="utf-8").format(**values)
    return FilledScenario(scenario=scenario, message=message, customer=customer, order=order, subscription=subscription)


def _pick_subscription() -> dict[str, Any]:
    subscription = pool.pick_subscription()
    if subscription is None:
        if not pool.seeded_subscriptions():
            raise ScenarioUnavailable("No sandbox subscriptions have been seeded yet.")
        raise ScenarioUnavailable(
            "Every seeded sandbox subscription has been cancelled or has a cancellation waiting on the "
            "Approvals page."
        )
    return subscription
