"""Offline tests for cleat.paypal.rest, with PayPal's HTTP endpoints replaced by fakes."""

import json
import uuid
from typing import Any

import pytest

from cleat.paypal import rest

SANDBOX = "https://api-m.sandbox.paypal.com"


class FakeResponse:
    """The parts of requests.Response that rest.py reads."""

    def __init__(self, status_code: int = 200, body: dict | None = None, headers: dict | None = None) -> None:
        self.status_code = status_code
        self._body = body
        self.headers = headers or {"Paypal-Debug-Id": "debug-123"}
        self.reason = "Fake reason"

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    @property
    def content(self) -> bytes:
        return b"" if self._body is None else json.dumps(self._body).encode()

    def json(self) -> Any:
        return self._body


class FakePayPal:
    """Records every request and answers API calls from a queue of prepared responses."""

    def __init__(self) -> None:
        self.token_requests = 0
        self.calls: list[dict[str, Any]] = []
        self.responses: list[FakeResponse] = []

    def token_endpoint(self, url: str, **kwargs: Any) -> FakeResponse:
        self.token_requests += 1
        self.calls.append({"method": "POST", "url": url, **kwargs})
        return FakeResponse(200, {"access_token": f"token-{self.token_requests}", "expires_in": 32400})

    def api(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        return self.responses.pop(0)


@pytest.fixture
def paypal(monkeypatch: pytest.MonkeyPatch) -> FakePayPal:
    fake = FakePayPal()
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "test-client")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "test-secret")
    monkeypatch.setattr(rest, "_token", None)
    monkeypatch.setattr(rest.requests, "post", fake.token_endpoint)
    monkeypatch.setattr(rest.requests, "request", fake.api)
    return fake


def _capture_body(capture_id: str = "CAP1") -> dict:
    return {"id": capture_id, "status": "COMPLETED", "amount": {"currency_code": "USD", "value": "45.00"}}


def test_token_is_fetched_once_and_reused(paypal: FakePayPal) -> None:
    paypal.responses = [FakeResponse(200, _capture_body()), FakeResponse(200, _capture_body())]
    rest.get_capture("CAP1")
    rest.get_capture("CAP1")
    assert paypal.token_requests == 1
    api_calls = [c for c in paypal.calls if "oauth2" not in c["url"]]
    assert {c["headers"]["Authorization"] for c in api_calls} == {"Bearer token-1"}


def test_every_request_goes_to_the_sandbox(paypal: FakePayPal) -> None:
    paypal.responses = [FakeResponse(200, _capture_body()), FakeResponse(201, {"id": "REF1", "status": "COMPLETED"})]
    rest.get_capture("CAP1")
    rest.refund_capture("CAP1", 5, "USD")
    assert paypal.calls and all(c["url"].startswith(SANDBOX + "/") for c in paypal.calls)


def test_posts_carry_a_unique_request_id_and_gets_carry_none(paypal: FakePayPal) -> None:
    paypal.responses = [
        FakeResponse(201, {"id": "REF1", "status": "COMPLETED"}),
        FakeResponse(201, {"id": "REF2", "status": "COMPLETED"}),
        FakeResponse(200, _capture_body()),
    ]
    first = rest.refund_capture("CAP1", 5, "USD")
    second = rest.refund_capture("CAP1", 5, "USD")
    rest.get_capture("CAP1")
    posts = [c for c in paypal.calls if c["method"] == "POST" and "oauth2" not in c["url"]]
    ids = [c["headers"]["PayPal-Request-Id"] for c in posts]
    assert len(set(ids)) == 2 and all(uuid.UUID(i) for i in ids)
    assert [first.request_id, second.request_id] == ids
    assert "PayPal-Request-Id" not in paypal.calls[-1]["headers"]


@pytest.mark.parametrize("rel", ["payer-action", "approve"])
def test_create_order_returns_the_approval_link(paypal: FakePayPal, rel: str) -> None:
    link = "https://www.sandbox.paypal.com/checkoutnow?token=ORD1"
    paypal.responses = [FakeResponse(201, {"id": "ORD1", "links": [{"rel": "self", "href": "x"}, {"rel": rel, "href": link}]})]
    order = rest.create_order(20, "USD", "Kantha stole", custom_id="KHC-001")
    assert (order.order_id, order.approve_url) == ("ORD1", link)
    sent = paypal.calls[-1]["json"]
    assert sent["intent"] == "CAPTURE"
    assert sent["purchase_units"][0]["amount"] == {"currency_code": "USD", "value": "20.00"}
    assert sent["purchase_units"][0]["custom_id"] == "KHC-001"


def test_capture_order_reads_the_capture_id(paypal: FakePayPal) -> None:
    body = {"id": "ORD1", "status": "COMPLETED", "purchase_units": [{"payments": {"captures": [_capture_body("CAP9")]}}]}
    paypal.responses = [FakeResponse(201, body)]
    captured = rest.capture_order("ORD1")
    assert (captured.order_id, captured.capture_id, captured.capture_status) == ("ORD1", "CAP9", "COMPLETED")
    assert paypal.calls[-1]["url"] == f"{SANDBOX}/v2/checkout/orders/ORD1/capture"


def test_refund_sends_the_amount_note_and_full_response_header(paypal: FakePayPal) -> None:
    paypal.responses = [FakeResponse(201, {"id": "REF1", "status": "COMPLETED"})]
    refund = rest.refund_capture("CAP1", "20", "USD", note="Torn scarf")
    call = paypal.calls[-1]
    assert call["url"] == f"{SANDBOX}/v2/payments/captures/CAP1/refund"
    assert call["json"] == {"amount": {"currency_code": "USD", "value": "20.00"}, "note_to_payer": "Torn scarf"}
    assert call["headers"]["Prefer"] == "return=representation"
    assert (refund.data["id"], refund.debug_id) == ("REF1", "debug-123")


def test_paypal_errors_keep_the_issue_and_debug_id(paypal: FakePayPal) -> None:
    body = {
        "name": "UNPROCESSABLE_ENTITY",
        "message": "The requested action could not be performed.",
        "debug_id": "abc123",
        "details": [{"issue": "ORDER_NOT_APPROVED", "description": "Payer has not yet approved the Order for payment."}],
    }
    paypal.responses = [FakeResponse(422, body)]
    with pytest.raises(rest.PayPalError) as caught:
        rest.capture_order("ORD1")
    error = caught.value
    assert (error.status_code, error.name, error.issue, error.debug_id) == (422, "UNPROCESSABLE_ENTITY", "ORDER_NOT_APPROVED", "abc123")
    assert error.request_id is not None


def test_a_rejected_token_is_refreshed_once_with_the_same_request_id(paypal: FakePayPal) -> None:
    paypal.responses = [FakeResponse(401, {"name": "AUTHENTICATION_FAILURE"}), FakeResponse(201, {"id": "REF1", "status": "COMPLETED"})]
    rest.refund_capture("CAP1", 5, "USD")
    attempts = [c for c in paypal.calls if "refund" in c["url"]]
    assert paypal.token_requests == 2
    assert attempts[0]["headers"]["PayPal-Request-Id"] == attempts[1]["headers"]["PayPal-Request-Id"]


@pytest.mark.parametrize("bad_id", ["../../v1/oauth2/token", "CAP1/refund", "CAP 1", ""])
def test_ids_that_could_change_the_url_are_refused(paypal: FakePayPal, bad_id: str) -> None:
    with pytest.raises(ValueError):
        rest.refund_capture(bad_id, 5, "USD")
    assert paypal.calls == []


@pytest.mark.parametrize(("amount", "expected"), [(20, "20.00"), ("19.999", "20.00"), (0.5, "0.50")])
def test_amounts_are_formatted_to_two_decimals(amount: object, expected: str) -> None:
    assert rest.format_amount(amount) == expected


@pytest.mark.parametrize("amount", [0, -5, "abc"])
def test_non_positive_or_invalid_amounts_are_refused(amount: object) -> None:
    with pytest.raises(ValueError):
        rest.format_amount(amount)


def test_create_subscription_returns_the_approval_link(paypal: FakePayPal) -> None:
    link = "https://www.sandbox.paypal.com/webapps/billing/subscriptions?ba_token=BA-1"
    paypal.responses = [FakeResponse(201, {"id": "I-SUB1", "status": "APPROVAL_PENDING",
                                           "links": [{"rel": "approve", "href": link}, {"rel": "self", "href": "x"}]})]
    created = rest.create_subscription("P-PLAN1", "Meera", "Chatterjee", "meera@example.com", "Kolkata Handloom Co.")
    assert (created.subscription_id, created.approve_url) == ("I-SUB1", link)
    call = paypal.calls[-1]
    assert call["url"] == f"{SANDBOX}/v1/billing/subscriptions"
    assert call["json"]["plan_id"] == "P-PLAN1"
    assert call["json"]["subscriber"]["email_address"] == "meera@example.com"


def test_monthly_plan_bills_the_price_every_month(paypal: FakePayPal) -> None:
    paypal.responses = [FakeResponse(201, {"id": "P-PLAN1", "status": "ACTIVE"})]
    rest.create_monthly_plan("PROD-1", "Monthly saree care", 12, "USD")
    cycle = paypal.calls[-1]["json"]["billing_cycles"][0]
    assert cycle["frequency"] == {"interval_unit": "MONTH", "interval_count": 1}
    assert cycle["pricing_scheme"]["fixed_price"] == {"value": "12.00", "currency_code": "USD"}


def test_cancel_subscription_accepts_paypals_empty_204(paypal: FakePayPal) -> None:
    paypal.responses = [FakeResponse(204, None)]
    resp = rest.cancel_subscription("I-SUB1", "No longer needed")
    call = paypal.calls[-1]
    assert call["url"] == f"{SANDBOX}/v1/billing/subscriptions/I-SUB1/cancel"
    assert call["json"] == {"reason": "No longer needed"}
    assert resp.data == {} and resp.request_id


def test_a_missing_subscription_raises_with_paypals_issue(paypal: FakePayPal) -> None:
    body = {"name": "RESOURCE_NOT_FOUND", "message": "The specified resource does not exist.", "debug_id": "nf1",
            "details": [{"issue": "INVALID_RESOURCE_ID", "description": "Requested resource ID was not found."}]}
    paypal.responses = [FakeResponse(404, body)]
    with pytest.raises(rest.PayPalError) as caught:
        rest.get_subscription("I-NOPE")
    assert (caught.value.status_code, caught.value.issue) == (404, "INVALID_RESOURCE_ID")
