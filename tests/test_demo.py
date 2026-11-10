"""Tests for the demo scenarios and the capture pool."""

import json
import string

import pytest

from cleat.demo import pool, scenarios
from cleat.store import db

pytestmark = pytest.mark.usefixtures("memory_db")

ORDERS = [
    {"seed": 1, "order_id": "ORD22", "capture_id": "CAP22", "capture_status": "COMPLETED", "amount": "22.00",
     "currency": "USD", "customer_name": "Ananya Bose", "customer_email": "a@example.com", "item": "Kantha stole"},
    {"seed": 2, "order_id": "ORD45", "capture_id": "CAP45", "capture_status": "COMPLETED", "amount": "45.00",
     "currency": "USD", "customer_name": "Priya Sen", "customer_email": "p@example.com", "item": "Silk scarf"},
    {"seed": 3, "order_id": "ORD240", "capture_id": "CAP240", "capture_status": "COMPLETED", "amount": "240.00",
     "currency": "USD", "customer_name": "Meera Chatterjee", "customer_email": "m@example.com", "item": "Baluchari saree"},
]


@pytest.fixture
def paypal_balances(monkeypatch: pytest.MonkeyPatch) -> dict[str, float]:
    """Seed the three orders and make PayPal report each capture's balance from the returned dict."""
    balances = {"CAP22": 22.0, "CAP45": 45.0, "CAP240": 240.0}
    monkeypatch.setattr(pool, "seeded_orders", lambda: [dict(order) for order in ORDERS])

    def position(capture_id: str) -> dict:
        left = balances[capture_id]
        return {"capture_status": "COMPLETED" if left > 0 else "REFUNDED", "remaining_refundable": left}

    monkeypatch.setattr(pool, "refund_position", position)
    return balances


def by_id(scenario_id: str) -> scenarios.Scenario:
    return next(s for s in scenarios.load_scenarios() if s.id == scenario_id)


@pytest.mark.usefixtures("paypal_balances")
def test_the_tightest_fitting_capture_is_chosen() -> None:
    assert pool.pick_capture(20)["capture_id"] == "CAP22"
    assert pool.pick_capture(180)["capture_id"] == "CAP240"
    assert pool.pick_capture(500) is None


def test_a_capture_paypal_says_is_used_up_is_skipped(paypal_balances: dict[str, float]) -> None:
    # Cleat's records know of no refunds (for example after a demo reset), but PayPal does.
    paypal_balances["CAP22"] = 0.0
    assert pool.pick_capture(20)["capture_id"] == "CAP45"


@pytest.mark.usefixtures("paypal_balances")
def test_refunds_through_cleat_reduce_the_estimated_balance() -> None:
    db.log_attempt(session_id="s", tool="refund_capture", tier="money", args_json=json.dumps({"capture_id": "CAP22"}),
                   decision="allow", reason="R1", facts_json="{}", amount=20.0, status="executed", executed_at=db.utcnow())
    assert pool.pick_capture(20)["capture_id"] == "CAP45"


@pytest.mark.usefixtures("paypal_balances")
def test_a_scenario_is_filled_with_a_real_order() -> None:
    filled = scenarios.fill(by_id("07"))
    assert filled.order["capture_id"] == "CAP45"
    assert "ORD45" in filled.message and "Priya Sen" in filled.message and "{" not in filled.message


def test_without_seeded_orders_scenarios_needing_one_are_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pool, "seeded_orders", list)
    monkeypatch.setattr(pool, "seeded_subscriptions", list)
    with pytest.raises(scenarios.ScenarioUnavailable, match="orders have been seeded yet"):
        scenarios.fill(by_id("03"))
    with pytest.raises(scenarios.ScenarioUnavailable, match="subscriptions have been seeded yet"):
        scenarios.fill(by_id("10"))


def test_when_every_order_is_used_up_the_message_says_so(paypal_balances: dict[str, float]) -> None:
    paypal_balances.update(CAP22=0.0, CAP45=0.0, CAP240=0.0)
    with pytest.raises(scenarios.ScenarioUnavailable, match=r"still has \$40.00"):
        scenarios.fill(by_id("03"))


def test_every_scenario_template_exists_and_uses_known_placeholders() -> None:
    known = {"customer_name", "order_id", "capture_id", "amount", "item", "subscription_id"}
    loaded = scenarios.load_scenarios()
    assert len({s.id for s in loaded}) == len(loaded)
    for scenario in loaded:
        text = (scenarios.EMAILS / scenario.template).read_text(encoding="utf-8")
        used = {name for _, name, _, _ in string.Formatter().parse(text) if name}
        assert used <= known, scenario.id
        assert scenario.expected in {"allow", "approve", "block"}


SUBSCRIPTIONS = [
    {"seed": 1, "subscription_id": "I-SUB1", "customer_name": "Meera Chatterjee"},
    {"seed": 2, "subscription_id": "I-SUB2", "customer_name": "Tanvi Dutta"},
]


@pytest.fixture
def paypal_subscriptions(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Seed two subscriptions and make PayPal report each one's status from the returned dict."""
    statuses = {"I-SUB1": "ACTIVE", "I-SUB2": "ACTIVE"}
    monkeypatch.setattr(pool, "seeded_subscriptions", lambda: [dict(s) for s in SUBSCRIPTIONS])
    monkeypatch.setattr(pool, "subscription_facts", lambda sub_id: {"subscription_status": statuses[sub_id]})
    return statuses


@pytest.mark.usefixtures("paypal_subscriptions")
@pytest.mark.parametrize("scenario_id", ["06", "10"])
def test_subscription_scenarios_use_a_real_seeded_subscription(scenario_id: str) -> None:
    filled = scenarios.fill(by_id(scenario_id))
    assert "I-SUB1" in filled.message and "{" not in filled.message
    assert filled.subscription["subscription_id"] == "I-SUB1"


def test_a_subscription_paypal_says_is_cancelled_is_skipped(paypal_subscriptions: dict[str, str]) -> None:
    paypal_subscriptions["I-SUB1"] = "CANCELLED"
    assert scenarios.fill(by_id("10")).customer == "Tanvi Dutta"


@pytest.mark.usefixtures("paypal_subscriptions")
def test_a_subscription_with_a_held_cancellation_is_not_offered_again() -> None:
    db.log_attempt(session_id="s", tool="cancel_subscription", tier="destructive",
                   args_json=json.dumps({"subscription_id": "I-SUB1"}), decision="approve", reason="R5",
                   facts_json="{}", status="held")
    assert scenarios.fill(by_id("10")).subscription["subscription_id"] == "I-SUB2"


def test_when_every_subscription_is_used_up_the_message_says_so(paypal_subscriptions: dict[str, str]) -> None:
    paypal_subscriptions.update({"I-SUB1": "CANCELLED", "I-SUB2": "CANCELLED"})
    with pytest.raises(scenarios.ScenarioUnavailable, match="has been cancelled"):
        scenarios.fill(by_id("10"))


@pytest.mark.usefixtures("paypal_balances")
def test_scenario_03_picks_a_capture_its_20_dollar_refund_only_partly_refunds() -> None:
    # The $22 order would be the tightest fit for $20, leaving $2: picked, it is not the demo we want.
    filled = scenarios.fill(by_id("03"))
    assert filled.order["capture_id"] == "CAP45"


def test_scenario_03_refund_is_partial_on_every_seeded_order_it_could_pick(monkeypatch: pytest.MonkeyPatch) -> None:
    # Checked against the real fixture: the template asks for "a $20 partial refund".
    real_orders = pool.seeded_orders()
    scenario = by_id("03")
    assert "$20 partial refund" in (scenarios.EMAILS / scenario.template).read_text(encoding="utf-8")
    eligible = [o for o in real_orders if float(o["amount"]) + 0.005 >= scenario.min_remaining]
    assert all(float(o["amount"]) >= 2 * 20 for o in eligible)
    if real_orders:
        monkeypatch.setattr(pool, "refund_position", lambda cap: {"capture_status": "COMPLETED", "remaining_refundable": 1e9})
        assert float(scenarios.fill(scenario).order["amount"]) > 20
