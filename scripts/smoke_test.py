"""End-to-end check of the PayPal plumbing: look up an order and a capture,
then refund $1 on one capture.

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
    """Run the three checks against the first seeded order."""
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
    print(
        "\nSmoke test passed. Confirm the refund in the sandbox: developer.paypal.com > Sandbox > "
        "Accounts > your Business account > View/Edit > activity, or log in to "
        "https://www.sandbox.paypal.com as the business account."
    )


if __name__ == "__main__":
    main()
