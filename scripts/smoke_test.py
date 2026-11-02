"""End-to-end check of the PayPal plumbing: look up an order and a capture,
refund $1 on one capture, and confirm the seeded subscriptions are active (read-only).

Run from the repo root after seeding:  python -m scripts.smoke_test
Exits with status 1 and the reason if any step fails.
"""

import json
import sys
from typing import NoReturn

from cleat.paypal import rest
from cleat.paypal.tools import raw_tools
from cleat.settings import ROOT

FIXTURES = ROOT / "data" / "fixtures" / "orders.json"
SUBSCRIPTION_FIXTURES = ROOT / "data" / "fixtures" / "subscriptions.json"
REFUND_AMOUNT = 1.00


def fail(message: str) -> NoReturn:
    """Stop the smoke test with a non-zero exit status."""
    sys.exit(f"FAILED: {message}")


def parse_tool_output(tool_name: str, output: str) -> dict:
    """Tools report errors as plain text, so anything that is not JSON is a failure."""
    try:
        return json.loads(output)
    except ValueError:
        fail(f"{tool_name} returned: {output}")


def main() -> None:
    """Run the order checks against the first seeded order, then check the subscriptions."""
    entries = json.loads(FIXTURES.read_text(encoding="utf-8")) if FIXTURES.exists() else []
    if not entries:
        fail("data/fixtures/orders.json has no orders. Run python -m scripts.seed_orders first.")
    entry = entries[0]
    tools = {tool.name: tool for tool in raw_tools()}

    order = parse_tool_output(
        "get_order_details", tools["get_order_details"].invoke({"order_id": entry["order_id"]})
    )
    if order.get("status") != "COMPLETED":
        fail(f"order {entry['order_id']} status is {order.get('status')}, expected COMPLETED")
    print(f"1. Toolkit get_order_details: order {entry['order_id']} is {order['status']} ({order['amount']})")

    capture = rest.get_capture(entry["capture_id"])
    amount = capture.data["amount"]
    print(
        f"2. Payments v2 get_capture: capture {entry['capture_id']} is {capture.data['status']}, "
        f"{amount['currency_code']} {amount['value']} [debug_id={capture.debug_id}]"
    )

    refund = parse_tool_output(
        "refund_capture",
        tools["refund_capture"].invoke(
            {"capture_id": entry["capture_id"], "amount": REFUND_AMOUNT, "currency": entry["currency"], "reason": "Cleat smoke test"}
        ),
    )
    if refund.get("status") not in {"COMPLETED", "PENDING"}:
        fail(f"refund status is {refund.get('status')}")
    print(
        f"3. refund_capture: refund {refund['refund_id']} is {refund['status']} "
        f"[request_id={refund['paypal_request_id']}, debug_id={refund['paypal_debug_id']}]"
    )

    after = rest.get_capture(entry["capture_id"])
    print(f"   Capture {entry['capture_id']} is now {after.data['status']}.")

    subs = (
        json.loads(SUBSCRIPTION_FIXTURES.read_text(encoding="utf-8")).get("subscriptions", [])
        if SUBSCRIPTION_FIXTURES.exists()
        else []
    )
    if not subs:
        fail("data/fixtures/subscriptions.json has no subscriptions. Run python -m scripts.seed_orders first.")
    statuses = {sub["subscription_id"]: rest.get_subscription(sub["subscription_id"]).data.get("status") for sub in subs}
    active = [sub_id for sub_id, status in statuses.items() if status == "ACTIVE"]
    print(f"4. Subscriptions v1: {len(active)} of {len(subs)} seeded subscriptions are ACTIVE: {statuses}")
    if not active:
        fail("no seeded subscription is ACTIVE, so scenario 10 cannot run. Seed more with python -m scripts.seed_orders.")
    print(
        "\nSmoke test passed. Confirm the refund in the sandbox: developer.paypal.com > Sandbox > "
        "Accounts > your Business account > View/Edit > activity, or log in to "
        "https://www.sandbox.paypal.com as the business account."
    )


if __name__ == "__main__":
    main()
