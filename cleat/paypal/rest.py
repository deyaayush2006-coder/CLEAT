"""Direct calls to the PayPal sandbox REST API: OAuth token cache, Orders v2
(create, capture), Payments v2 (get capture, refund capture) and Subscriptions v1
(product, plan and subscription for the demo; get and cancel subscription).

Every POST carries a fresh PayPal-Request-Id, so PayPal treats a retried request as the
same request instead of creating a second order, capture or refund.
"""

import re
import time
import uuid
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

import requests

from cleat.settings import PAYPAL_BASE_URL, require

TIMEOUT_SECONDS = 30
# Refresh early so a cached token never expires between the check and the request.
TOKEN_EXPIRY_MARGIN_SECONDS = 60
# PayPal needs somewhere to send the buyer after approval. Cleat captures through the API,
# so the page itself never has to exist.
RETURN_URL = "https://example.com/cleat/approved"
CANCEL_URL = "https://example.com/cleat/cancelled"
# IDs are interpolated into URL paths, so anything but plain PayPal-style IDs is refused.
_PAYPAL_ID = re.compile(r"[A-Za-z0-9-]{1,64}")


@dataclass(frozen=True)
class PayPalResponse:
    """A successful PayPal response plus the IDs that trace it in PayPal's logs."""

    data: dict[str, Any]
    request_id: str | None
    debug_id: str | None


@dataclass(frozen=True)
class CreatedOrder:
    """An order waiting for the buyer to approve it at approve_url."""

    order_id: str
    approve_url: str
    response: PayPalResponse


@dataclass(frozen=True)
class CapturedOrder:
    """An order whose payment has been captured."""

    order_id: str
    capture_id: str
    capture_status: str
    response: PayPalResponse


class PayPalError(Exception):
    """A PayPal call failed. `issue` holds PayPal's specific error code when it sends one."""

    def __init__(
        self,
        status_code: int,
        name: str,
        message: str,
        issue: str | None = None,
        debug_id: str | None = None,
        request_id: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.name = name
        self.issue = issue
        self.debug_id = debug_id
        self.request_id = request_id
        detail = f"{name} ({issue})" if issue else name
        super().__init__(f"PayPal {status_code} {detail}: {message} [debug_id={debug_id}]")


_token: tuple[str, float] | None = None


def get_token() -> str:
    """Return an OAuth access token, reusing the cached one until shortly before it expires."""
    global _token
    if _token and time.monotonic() < _token[1]:
        return _token[0]
    resp = requests.post(
        f"{PAYPAL_BASE_URL}/v1/oauth2/token",
        auth=(require("PAYPAL_CLIENT_ID"), require("PAYPAL_CLIENT_SECRET")),
        data={"grant_type": "client_credentials"},
        headers={"Accept": "application/json"},
        timeout=TIMEOUT_SECONDS,
    )
    body = _parse(resp, request_id=None)
    _token = (body["access_token"], time.monotonic() + body["expires_in"] - TOKEN_EXPIRY_MARGIN_SECONDS)
    return _token[0]


def create_order(amount: Decimal | float | str, currency: str, description: str, custom_id: str | None = None) -> CreatedOrder:
    """Create a CAPTURE-intent order and return its ID and the buyer's approval link."""
    purchase_unit: dict[str, Any] = {
        "amount": {"currency_code": currency, "value": format_amount(amount)},
        "description": description[:127],
    }
    if custom_id:
        purchase_unit["custom_id"] = custom_id
    body = {
        "intent": "CAPTURE",
        "purchase_units": [purchase_unit],
        "payment_source": {
            "paypal": {"experience_context": {"return_url": RETURN_URL, "cancel_url": CANCEL_URL}}
        },
    }
    resp = _call("POST", "/v2/checkout/orders", body)
    # PayPal names the link "payer-action" when payment_source is sent and "approve" otherwise.
    approve_url = next(
        (link["href"] for link in resp.data.get("links", []) if link.get("rel") in {"payer-action", "approve"}),
        None,
    )
    if approve_url is None:
        raise PayPalError(201, "MISSING_APPROVAL_LINK", "Order created without an approval link",
                          debug_id=resp.debug_id, request_id=resp.request_id)
    return CreatedOrder(order_id=resp.data["id"], approve_url=approve_url, response=resp)


def capture_order(order_id: str) -> CapturedOrder:
    """Capture an approved order. Raises PayPalError with issue ORDER_NOT_APPROVED if the buyer has not approved it."""
    resp = _call("POST", f"/v2/checkout/orders/{_checked_id(order_id)}/capture", {})
    capture = resp.data["purchase_units"][0]["payments"]["captures"][0]
    return CapturedOrder(order_id=resp.data["id"], capture_id=capture["id"], capture_status=capture["status"], response=resp)


def get_order(order_id: str) -> PayPalResponse:
    """Return an order's details, including every capture and refund made against it."""
    return _call("GET", f"/v2/checkout/orders/{_checked_id(order_id)}")


def get_capture(capture_id: str) -> PayPalResponse:
    """Return a captured payment's details: amount, status and links."""
    return _call("GET", f"/v2/payments/captures/{_checked_id(capture_id)}")


def refund_capture(capture_id: str, amount: Decimal | float | str, currency: str, note: str = "") -> PayPalResponse:
    """Refund part or all of a captured payment. `note` is shown to the buyer."""
    body: dict[str, Any] = {"amount": {"currency_code": currency, "value": format_amount(amount)}}
    if note:
        body["note_to_payer"] = note[:255]
    return _call("POST", f"/v2/payments/captures/{_checked_id(capture_id)}/refund", body)


@dataclass(frozen=True)
class CreatedSubscription:
    """A subscription waiting for the buyer to approve it at approve_url."""

    subscription_id: str
    approve_url: str
    response: PayPalResponse


def create_product(name: str, description: str = "") -> PayPalResponse:
    """Create a catalog product (Catalog Products v1), the parent of a subscription plan."""
    body: dict[str, Any] = {"name": name[:127], "type": "SERVICE", "category": "SERVICES"}
    if description:
        body["description"] = description[:256]
    return _call("POST", "/v1/catalogs/products", body)


def create_monthly_plan(product_id: str, name: str, price: Decimal | float | str, currency: str) -> PayPalResponse:
    """Create an ACTIVE plan that bills `price` every month until cancelled."""
    body = {
        "product_id": _checked_id(product_id),
        "name": name[:127],
        "status": "ACTIVE",
        "billing_cycles": [
            {
                "frequency": {"interval_unit": "MONTH", "interval_count": 1},
                "tenure_type": "REGULAR",
                "sequence": 1,
                "total_cycles": 0,
                "pricing_scheme": {"fixed_price": {"value": format_amount(price), "currency_code": currency}},
            }
        ],
        "payment_preferences": {"auto_bill_outstanding": True, "payment_failure_threshold": 1},
    }
    return _call("POST", "/v1/billing/plans", body)


def create_subscription(plan_id: str, given_name: str, surname: str, email: str, brand: str) -> CreatedSubscription:
    """Create a subscription to a plan and return its ID and the buyer's approval link."""
    body = {
        "plan_id": _checked_id(plan_id),
        "subscriber": {"name": {"given_name": given_name, "surname": surname}, "email_address": email},
        "application_context": {
            "brand_name": brand[:127],
            "shipping_preference": "NO_SHIPPING",
            "user_action": "SUBSCRIBE_NOW",
            "return_url": RETURN_URL,
            "cancel_url": CANCEL_URL,
        },
    }
    resp = _call("POST", "/v1/billing/subscriptions", body)
    approve_url = next((link["href"] for link in resp.data.get("links", []) if link.get("rel") == "approve"), None)
    if approve_url is None:
        raise PayPalError(201, "MISSING_APPROVAL_LINK", "Subscription created without an approval link",
                          debug_id=resp.debug_id, request_id=resp.request_id)
    return CreatedSubscription(subscription_id=resp.data["id"], approve_url=approve_url, response=resp)


def get_subscription(subscription_id: str) -> PayPalResponse:
    """Return a subscription's details, including its status (ACTIVE, CANCELLED, ...)."""
    return _call("GET", f"/v1/billing/subscriptions/{_checked_id(subscription_id)}")


def cancel_subscription(subscription_id: str, reason: str) -> PayPalResponse:
    """Cancel an ACTIVE or SUSPENDED subscription. PayPal answers 204 with no body."""
    body = {"reason": (reason or "Cancelled by the store")[:127]}
    return _call("POST", f"/v1/billing/subscriptions/{_checked_id(subscription_id)}/cancel", body)


def format_amount(amount: Decimal | float | str) -> str:
    """Format a positive amount the way PayPal expects for two-decimal currencies such as USD."""
    try:
        value = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        raise ValueError(f"Not a valid amount: {amount!r}") from None
    if value <= 0:
        raise ValueError(f"Amount must be greater than zero, got {amount!r}")
    return f"{value:.2f}"


def _checked_id(paypal_id: str) -> str:
    if not _PAYPAL_ID.fullmatch(paypal_id):
        raise ValueError(f"Not a valid PayPal ID: {paypal_id!r}")
    return paypal_id


def _call(method: str, path: str, body: dict[str, Any] | None = None) -> PayPalResponse:
    global _token
    request_id = str(uuid.uuid4()) if method == "POST" else None
    for attempt in range(2):
        headers = {
            "Authorization": f"Bearer {get_token()}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }
        if request_id:
            headers["PayPal-Request-Id"] = request_id
        resp = requests.request(method, f"{PAYPAL_BASE_URL}{path}", headers=headers, json=body, timeout=TIMEOUT_SECONDS)
        # A token revoked before its expiry gets one refresh; reusing the request ID keeps the retry idempotent.
        if resp.status_code == 401 and attempt == 0:
            _token = None
            continue
        break
    return PayPalResponse(data=_parse(resp, request_id), request_id=request_id, debug_id=resp.headers.get("Paypal-Debug-Id"))


def _parse(resp: requests.Response, request_id: str | None) -> dict[str, Any]:
    try:
        body = resp.json() if resp.content else {}
    except ValueError:
        body = {}
    if resp.ok:
        return body
    details = body.get("details") or [{}]
    raise PayPalError(
        status_code=resp.status_code,
        # OAuth errors use "error"/"error_description"; REST API errors use "name"/"message"/"details".
        name=body.get("name") or body.get("error") or "HTTP_ERROR",
        message=details[0].get("description") or body.get("message") or body.get("error_description") or resp.reason,
        issue=details[0].get("issue"),
        debug_id=body.get("debug_id") or resp.headers.get("Paypal-Debug-Id"),
        request_id=request_id,
    )
