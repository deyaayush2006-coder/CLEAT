"""Offline tests for scripts/seed_orders.py, with PayPal, the browser and the keyboard faked."""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from cleat.paypal import rest
from scripts import seed_orders


class FakeSeedPayPal:
    """Stands in for the rest calls the seed script makes and records what it was asked."""

    def __init__(self) -> None:
        self.created: list[str] = []
        self.statuses: dict[str, list[str]] = {}
        self.not_approved_once: set[str] = set()

    def _resp(self, data: dict[str, Any]) -> rest.PayPalResponse:
        return rest.PayPalResponse(data=data, request_id="req", debug_id="dbg")

    def create_order(self, amount: str, currency: str, description: str, custom_id: str | None = None) -> rest.CreatedOrder:
        order_id = f"ORD{len(self.created) + 1}"
        self.created.append(order_id)
        return rest.CreatedOrder(order_id, f"https://approve/{order_id}", self._resp({"id": order_id}))

    def capture_order(self, order_id: str) -> rest.CapturedOrder:
        if order_id in self.not_approved_once:
            self.not_approved_once.discard(order_id)
            raise rest.PayPalError(422, "UNPROCESSABLE_ENTITY", "Not approved", issue="ORDER_NOT_APPROVED")
        return rest.CapturedOrder(order_id, f"CAP-{order_id}", "COMPLETED", self._resp({}))

    def create_product(self, name: str, description: str = "") -> rest.PayPalResponse:
        self.created.append("PROD-1")
        return self._resp({"id": "PROD-1"})

    def create_monthly_plan(self, product_id: str, name: str, price: str, currency: str) -> rest.PayPalResponse:
        self.created.append("P-1")
        return self._resp({"id": "P-1"})

    def create_subscription(self, plan_id: str, given: str, surname: str, email: str, brand: str) -> rest.CreatedSubscription:
        sub_id = f"I-{given.upper()}"
        self.created.append(sub_id)
        self.statuses.setdefault(sub_id, ["ACTIVE"])
        return rest.CreatedSubscription(sub_id, f"https://approve/{sub_id}", self._resp({"id": sub_id}))

    def get_subscription(self, subscription_id: str) -> rest.PayPalResponse:
        queue = self.statuses[subscription_id]
        status = queue.pop(0) if len(queue) > 1 else queue[0]
        return self._resp({"id": subscription_id, "status": status})


@pytest.fixture
def seeding(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[tuple[FakeSeedPayPal, list[str]]]:
    """Fake PayPal and the browser, point the fixtures at tmp_path, and feed answers to input()."""
    fake = FakeSeedPayPal()
    for name in ("create_order", "capture_order", "create_product", "create_monthly_plan",
                 "create_subscription", "get_subscription"):
        monkeypatch.setattr(rest, name, getattr(fake, name))
    monkeypatch.setattr(seed_orders, "ROOT", tmp_path)
    monkeypatch.setattr(seed_orders, "FIXTURES", tmp_path / "orders.json")
    monkeypatch.setattr(seed_orders, "SUBSCRIPTION_FIXTURES", tmp_path / "subscriptions.json")
    monkeypatch.setattr(seed_orders.webbrowser, "open", lambda url: True)
    answers: list[str] = []
    monkeypatch.setattr("builtins.input", lambda prompt="": answers.pop(0) if answers else "")
    yield fake, answers


def test_orders_are_captured_after_approval_and_recorded(seeding: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    fake, answers = seeding
    monkeypatch.setattr(seed_orders, "CATALOGUE", seed_orders.CATALOGUE[:3])
    fake.not_approved_once.add("ORD2")  # the buyer pressed Enter before approving order 2
    answers.extend(["", "", "", "s"])  # order 1; order 2 twice; order 3 skipped
    seed_orders.seed_orders()
    saved = json.loads(seed_orders.FIXTURES.read_text(encoding="utf-8"))
    assert [(e["seed"], e["capture_id"]) for e in saved] == [(1, "CAP-ORD1"), (2, "CAP-ORD2")]


def test_rerunning_only_creates_what_is_missing(seeding: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    fake, _ = seeding
    monkeypatch.setattr(seed_orders, "CATALOGUE", seed_orders.CATALOGUE[:2])
    monkeypatch.setattr(seed_orders, "SUBSCRIBERS", seed_orders.SUBSCRIBERS[:2])
    seed_orders.main()
    first_run = list(fake.created)
    seed_orders.main()
    assert fake.created == first_run
    assert first_run.count("PROD-1") == 1 and first_run.count("P-1") == 1


def test_subscriptions_are_saved_only_once_paypal_says_active(seeding: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    fake, answers = seeding
    monkeypatch.setattr(seed_orders, "SUBSCRIBERS", [("Meera", "Chatterjee"), ("Tanvi", "Dutta")])
    fake.statuses["I-MEERA"] = ["APPROVAL_PENDING", "APPROVED", "ACTIVE"]
    answers.extend(["", "", "", "s"])  # Meera checked three times; Tanvi skipped
    seed_orders.seed_subscriptions()
    data = json.loads(seed_orders.SUBSCRIPTION_FIXTURES.read_text(encoding="utf-8"))
    assert (data["product_id"], data["plan_id"]) == ("PROD-1", "P-1")
    assert [(s["subscription_id"], s["status"], s["customer_name"]) for s in data["subscriptions"]] == [
        ("I-MEERA", "ACTIVE", "Meera Chatterjee")
    ]


def test_quitting_keeps_what_was_already_saved(seeding: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    _, answers = seeding
    monkeypatch.setattr(seed_orders, "SUBSCRIBERS", [("Meera", "Chatterjee"), ("Tanvi", "Dutta")])
    answers.extend(["", "q"])
    with pytest.raises(SystemExit):
        seed_orders.seed_subscriptions()
    data = json.loads(seed_orders.SUBSCRIPTION_FIXTURES.read_text(encoding="utf-8"))
    assert [s["subscription_id"] for s in data["subscriptions"]] == ["I-MEERA"]


def test_the_subscription_fixture_matches_what_the_demo_pool_reads(seeding: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    from cleat.demo import pool

    monkeypatch.setattr(seed_orders, "SUBSCRIBERS", [("Meera", "Chatterjee")])
    seed_orders.seed_subscriptions()
    monkeypatch.setattr(pool, "SUBSCRIPTION_FIXTURES", seed_orders.SUBSCRIPTION_FIXTURES)
    assert pool.seeded_subscriptions()[0]["subscription_id"] == "I-MEERA"


def test_the_catalogue_has_45_orders_with_15_high_value_ones_appended() -> None:
    catalogue = seed_orders.CATALOGUE
    assert len(catalogue) == 45
    assert len({(customer, item) for customer, item, _ in catalogue}) == 45
    assert all(200 <= float(amount) <= 400 for _, _, amount in catalogue[30:])
    # The original 30 keep their positions, so fixtures seeded from them stay valid.
    assert catalogue[0] == ("Ananya Bose", "Kantha stitch cotton stole", "22.00")
    assert catalogue[29] == ("Labanya Sen", "Kantha quilted baby blanket", "45.00")


def test_there_are_12_distinct_subscribers() -> None:
    names = [f"{given} {surname}" for given, surname in seed_orders.SUBSCRIBERS]
    assert len(names) == len(set(names)) == 12
    assert seed_orders.SUBSCRIBERS[:5] == [("Meera", "Chatterjee"), ("Tanvi", "Dutta"), ("Shreya", "Sinha"),
                                           ("Kritika", "Sengupta"), ("Ankita", "Roychowdhury")]


def _recorded_order(seed: int) -> dict:
    customer, item, amount = seed_orders.CATALOGUE[seed - 1]
    return {"seed": seed, "order_id": f"OLD{seed}", "capture_id": f"OLDCAP{seed}", "capture_status": "COMPLETED",
            "amount": rest.format_amount(amount), "currency": "USD", "customer_name": customer,
            "customer_email": "x@example.com", "item": item}


def test_resuming_after_the_first_30_orders_seeds_only_the_new_15(seeding: tuple) -> None:
    fake, _ = seeding
    seed_orders.save_fixtures([_recorded_order(seed) for seed in range(1, 31)])
    seed_orders.seed_orders()
    saved = json.loads(seed_orders.FIXTURES.read_text(encoding="utf-8"))
    assert [e["seed"] for e in saved] == list(range(1, 46))
    assert len(fake.created) == 15
    assert saved[30]["customer_name"] == seed_orders.CATALOGUE[30][0]
    assert all(200 <= float(e["amount"]) <= 400 for e in saved[30:])


def test_a_fixture_that_no_longer_matches_the_catalogue_stops_the_script(seeding: tuple) -> None:
    fake, _ = seeding
    wrong = _recorded_order(3)
    wrong["item"] = "Something that was reordered"
    seed_orders.save_fixtures([wrong])
    with pytest.raises(SystemExit, match="Append new orders"):
        seed_orders.seed_orders()
    assert fake.created == []


def test_a_subscription_fixture_that_no_longer_matches_stops_the_script(seeding: tuple) -> None:
    fake, _ = seeding
    seed_orders.save_subscription_fixtures({"product_id": "PROD-1", "plan_id": "P-1", "subscriptions": [
        {"seed": 1, "subscription_id": "I-OLD", "customer_name": "Someone Else"}]})
    with pytest.raises(SystemExit, match="Append new subscribers"):
        seed_orders.seed_subscriptions()
    assert fake.created == []
