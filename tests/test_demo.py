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
    with pytest.raises(scenarios.NoCaptureAvailable, match="seeded yet"):
        scenarios.fill(by_id("03"))
    assert scenarios.fill(by_id("06")).customer == "A customer"


def test_when_every_order_is_used_up_the_message_says_so(paypal_balances: dict[str, float]) -> None:
    paypal_balances.update(CAP22=0.0, CAP45=0.0, CAP240=0.0)
    with pytest.raises(scenarios.NoCaptureAvailable, match=r"still has \$20.00"):
        scenarios.fill(by_id("03"))


def test_every_scenario_template_exists_and_uses_known_placeholders() -> None:
    known = {"customer_name", "order_id", "capture_id", "amount", "item"}
    loaded = scenarios.load_scenarios()
    assert len({s.id for s in loaded}) == len(loaded)
    for scenario in loaded:
        text = (scenarios.EMAILS / scenario.template).read_text(encoding="utf-8")
        used = {name for _, name, _, _ in string.Formatter().parse(text) if name}
        assert used <= known, scenario.id
        assert scenario.expected in {"allow", "approve", "block"}
