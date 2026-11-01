"""Test setup shared by every test module."""

import os
from collections.abc import Callable, Iterable
from typing import Any

import pytest

# cleat.settings refuses to import unless PAYPAL_ENV is "sandbox". setdefault keeps any value
# already in the environment, so a shell that says otherwise still fails loudly.
os.environ.setdefault("PAYPAL_ENV", "sandbox")

from cleat.paypal import rest  # noqa: E402  must follow the PAYPAL_ENV default above
from cleat.store import db  # noqa: E402

SANDBOX = "https://api-m.sandbox.paypal.com"


@pytest.fixture
def memory_db() -> None:
    """Give the test its own empty in-memory database."""
    db.use_database("sqlite://")


@pytest.fixture
def fake_paypal(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    """Return a function that makes PayPal report one capture (CAP1, on order ORD1)."""

    def configure(captured: str = "45.00", status: str = "COMPLETED", refunds: Iterable[str] = ()) -> None:
        capture = {
            "id": "CAP1",
            "status": status,
            "amount": {"currency_code": "USD", "value": captured},
            "links": [{"rel": "up", "href": f"{SANDBOX}/v2/checkout/orders/ORD1"}],
        }
        order: dict[str, Any] = {
            "id": "ORD1",
            "purchase_units": [
                {
                    "payments": {
                        "refunds": [
                            {
                                "status": "COMPLETED",
                                "amount": {"currency_code": "USD", "value": value},
                                "links": [{"rel": "up", "href": f"{SANDBOX}/v2/payments/captures/CAP1"}],
                            }
                            for value in refunds
                        ]
                    }
                }
            ],
        }
        monkeypatch.setattr(rest, "get_capture", lambda capture_id: rest.PayPalResponse(capture, None, "debug-cap"))
        monkeypatch.setattr(rest, "get_order", lambda order_id: rest.PayPalResponse(order, None, "debug-ord"))

    return configure
