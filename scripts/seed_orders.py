"""Creates the demo store's sandbox data, waiting for manual buyer approval of each item:

1. 45 orders, captured and recorded in data/fixtures/orders.json.
2. One product and one monthly plan, then 12 subscriptions to it, checked ACTIVE with PayPal
   and recorded in data/fixtures/subscriptions.json (scenarios 06 and 10 use them).

Run from the repo root:  python -m scripts.seed_orders
Log in to https://www.sandbox.paypal.com as your sandbox Personal (buyer) account first.
Everything already in the fixture files is skipped, so the script can be stopped and rerun.
"""

import json
import webbrowser
from pathlib import Path
from typing import Any

from cleat.paypal import rest
from cleat.settings import ROOT

STORE = "Kolkata Handloom Co."
CURRENCY = "USD"
FIXTURES = ROOT / "data" / "fixtures" / "orders.json"
SUBSCRIPTION_FIXTURES = ROOT / "data" / "fixtures" / "subscriptions.json"

PRODUCT_NAME = "Saree care service"
PLAN_NAME = "Monthly saree care"
PLAN_PRICE = "12.00"
# Each approved cancellation in scenario 10 uses one up for good, so seed enough for the
# video, rehearsals and judges trying it until judging ends. Append new rows only: a
# subscriber's seed is its position here, and resuming relies on it.
SUBSCRIBERS: list[tuple[str, str]] = [
    ("Meera", "Chatterjee"),
    ("Tanvi", "Dutta"),
    ("Shreya", "Sinha"),
    ("Kritika", "Sengupta"),
    ("Ankita", "Roychowdhury"),
    ("Pooja", "Nandi"),
    ("Ishita", "Ghosh"),
    ("Riya", "Basu"),
    ("Sneha", "Majumdar"),
    ("Moumita", "Halder"),
    ("Nandini", "Biswas"),
    ("Debjani", "Pal"),
]

# Fictional customers. Amounts span $15-$300 with several large orders, because the
# demo scenarios need captures with $180+ of refundable balance.
CATALOGUE: list[tuple[str, str, str]] = [
    ("Ananya Bose", "Kantha stitch cotton stole", "22.00"),
    ("Rohan Mukherjee", "Handwoven jute tote bag", "15.00"),
    ("Priya Sen", "Murshidabad silk scarf", "45.00"),
    ("Arjun Banerjee", "Khadi cotton kurta", "38.00"),
    ("Meera Chatterjee", "Baluchari silk saree", "240.00"),
    ("Sourav Das", "Block-printed cushion covers, set of two", "28.00"),
    ("Ishita Ghosh", "Jamdani cotton dupatta", "65.00"),
    ("Kabir Roy", "Handloom Tant saree", "85.00"),
    ("Tanvi Dutta", "Garad silk saree", "195.00"),
    ("Nikhil Sarkar", "Kantha quilt, queen size", "180.00"),
    ("Riya Basu", "Madur grass table mats, set of six", "30.00"),
    ("Aditya Mitra", "Tussar silk stole", "55.00"),
    ("Sneha Majumdar", "Dhakai Jamdani saree", "300.00"),
    ("Vikram Saha", "Handwoven cotton bedsheet", "48.00"),
    ("Pooja Nandi", "Kantha embroidered jacket", "120.00"),
    ("Debjani Pal", "Batik silk table runner", "35.00"),
    ("Rahul Guha", "Muslin cotton shawl", "75.00"),
    ("Shreya Sinha", "Bishnupuri silk saree", "210.00"),
    ("Amitava Kar", "Handloom cotton napkins, set of six", "18.00"),
    ("Moumita Halder", "Ikat cotton cushion cover", "25.00"),
    ("Sayan Chakraborty", "Kantha stitch silk saree", "260.00"),
    ("Nandini Biswas", "Khadi linen shirt", "42.00"),
    ("Arnab Ganguly", "Handwoven wool throw", "95.00"),
    ("Kritika Sengupta", "Murshidabad silk saree", "185.00"),
    ("Suman Paul", "Jute and cotton floor rug", "150.00"),
    ("Brishti Lahiri", "Tant cotton dupatta", "20.00"),
    ("Joydeep Bhattacharya", "Matka silk stole", "60.00"),
    ("Ankita Roychowdhury", "Baluchari silk saree, festive edition", "290.00"),
    ("Prosenjit Mondal", "Handloom cotton towels, set of four", "32.00"),
    ("Labanya Sen", "Kantha quilted baby blanket", "45.00"),
    # Added before the first seeding run: high-value orders ($200-$400) so the scenarios that
    # need a large refundable balance (04 needs $180) keep working after many demo runs.
    # Append new rows only: an order's seed is its position here, and resuming relies on it.
    ("Rituparna Ghoshal", "Baluchari silk saree, wedding edition", "385.00"),
    ("Abhijit Sanyal", "Kantha stitch silk wedding shawl", "220.00"),
    ("Madhuja Bagchi", "Dhakai Jamdani saree, fine count", "340.00"),
    ("Subhankar Dey", "Handwoven Tussar silk sherwani fabric", "265.00"),
    ("Paromita Bhowmick", "Swarnachari silk saree", "310.00"),
    ("Indranil Sarkar", "Nakshi kantha wall hanging, large", "235.00"),
    ("Sohini Mitra", "Garad silk saree with zari border", "295.00"),
    ("Tathagata Roy", "Hand-embroidered kantha quilt, king size", "360.00"),
    ("Aparajita Basu", "Murshidabad silk saree, bridal", "400.00"),
    ("Kaushik Dasgupta", "Handloom Tant saree set of three", "210.00"),
    ("Debolina Chakraborty", "Bishnupuri silk saree with silver zari", "330.00"),
    ("Sudipto Banerjee", "Handwoven Matka silk dhoti and stole set", "245.00"),
    ("Anwesha Kundu", "Jamdani silk saree, heritage weave", "375.00"),
    ("Ritwik Majumdar", "Kantha stitch silk jacket, bespoke", "280.00"),
    ("Urmila Chowdhury", "Baluchari silk saree, Mahabharata motif", "350.00"),
]


def load_fixtures() -> list[dict]:
    """Return the captured orders recorded so far."""
    return json.loads(FIXTURES.read_text(encoding="utf-8")) if FIXTURES.exists() else []


def save_fixtures(entries: list[dict]) -> None:
    """Write the fixture file; called after every capture so an interruption loses nothing."""
    _write_json(FIXTURES, entries)


def check_orders_match_catalogue(entries: list[dict]) -> None:
    """Stop if a recorded order no longer matches its catalogue row.

    Resuming skips catalogue rows by seed (their position), so a reordered or edited catalogue
    would silently mismatch the fixtures. New orders must be appended to CATALOGUE.
    """
    for entry in entries:
        seed = entry["seed"]
        row = CATALOGUE[seed - 1] if 1 <= seed <= len(CATALOGUE) else None
        recorded = (entry["customer_name"], entry["item"], entry["amount"])
        if row is None or recorded != (row[0], row[1], rest.format_amount(row[2])):
            raise SystemExit(
                f"Order seed {seed} in {FIXTURES.name} is {recorded}, but CATALOGUE row {seed} is {row}. "
                "Append new orders to the end of CATALOGUE instead of inserting or reordering them."
            )


def check_subscriptions_match_subscribers(entries: list[dict]) -> None:
    """Stop if a recorded subscription no longer matches its SUBSCRIBERS row (see above)."""
    for entry in entries:
        seed = entry["seed"]
        row = SUBSCRIBERS[seed - 1] if 1 <= seed <= len(SUBSCRIBERS) else None
        if row is None or entry["customer_name"] != f"{row[0]} {row[1]}":
            raise SystemExit(
                f"Subscription seed {seed} in {SUBSCRIPTION_FIXTURES.name} is {entry['customer_name']!r}, but "
                f"SUBSCRIBERS row {seed} is {row}. Append new subscribers to the end instead of reordering them."
            )


def ask(prompt: str) -> str:
    """Read one answer; q stops the script so it can be rerun later."""
    answer = input(prompt).strip().lower()
    if answer == "q":
        raise SystemExit("Stopped. Run the script again to continue where you left off.")
    return answer


def capture_when_approved(order_id: str) -> rest.CapturedOrder | None:
    """Prompt until the buyer has approved the order, then capture it. Returns None if skipped."""
    while True:
        if ask("  Approve it in the browser, then press Enter (s = skip, q = quit): ") == "s":
            return None
        try:
            return rest.capture_order(order_id)
        except rest.PayPalError as e:
            if e.issue != "ORDER_NOT_APPROVED":
                raise
            print("  PayPal says this order is not approved yet.")


def seed_orders() -> None:
    """Create, approve (by hand) and capture every catalogue order not yet in the fixtures."""
    entries = load_fixtures()
    check_orders_match_catalogue(entries)
    done = {entry["seed"] for entry in entries}
    todo = [(seed, row) for seed, row in enumerate(CATALOGUE, start=1) if seed not in done]
    print(f"{len(done)} of {len(CATALOGUE)} orders already captured, {len(todo)} to go.\n")

    for position, (seed, (customer, item, amount)) in enumerate(todo, start=1):
        order = rest.create_order(amount, CURRENCY, f"{STORE}: {item}", custom_id=f"KHC-{seed:03d}")
        print(f"[{position}/{len(todo)}] ${amount} {item} for {customer}")
        print(f"  order {order.order_id}: {order.approve_url}")
        webbrowser.open(order.approve_url)
        captured = capture_when_approved(order.order_id)
        if captured is None:
            print("  Skipped.\n")
            continue
        entries.append(
            {
                "seed": seed,
                "order_id": captured.order_id,
                "capture_id": captured.capture_id,
                "capture_status": captured.capture_status,
                "amount": rest.format_amount(amount),
                "currency": CURRENCY,
                "customer_name": customer,
                "customer_email": customer.lower().replace(" ", ".") + "@example.com",
                "item": item,
            }
        )
        save_fixtures(entries)
        print(f"  Captured: {captured.capture_id} ({captured.capture_status})\n")

    print(f"Orders done. {len(entries)} captured orders in {FIXTURES.relative_to(ROOT).as_posix()}.\n")


def load_subscription_fixtures() -> dict[str, Any]:
    """Return the recorded product, plan and subscriptions."""
    if SUBSCRIPTION_FIXTURES.exists():
        return json.loads(SUBSCRIPTION_FIXTURES.read_text(encoding="utf-8"))
    return {"product_id": None, "plan_id": None, "subscriptions": []}


def save_subscription_fixtures(data: dict[str, Any]) -> None:
    """Write the subscription fixture file; called after every step so an interruption loses nothing."""
    _write_json(SUBSCRIPTION_FIXTURES, data)


def active_when_approved(subscription_id: str) -> str | None:
    """Prompt until PayPal reports the subscription ACTIVE. Returns its status, or None if skipped."""
    while True:
        if ask("  Approve it in the browser, then press Enter (s = skip, q = quit): ") == "s":
            return None
        status = rest.get_subscription(subscription_id).data.get("status")
        if status == "ACTIVE":
            return status
        if status == "APPROVAL_PENDING":
            print("  PayPal says this subscription is not approved yet.")
        else:
            print(f"  PayPal reports it as {status}; it should become ACTIVE within a few seconds.")


def seed_subscriptions() -> None:
    """Create the product and plan once, then subscribe each demo subscriber not yet recorded."""
    data = load_subscription_fixtures()
    if not data.get("product_id"):
        product = rest.create_product(PRODUCT_NAME, f"{STORE}: monthly cleaning and storage for handloom sarees")
        data["product_id"] = product.data["id"]
        save_subscription_fixtures(data)
        print(f"Created product {data['product_id']}.")
    if not data.get("plan_id"):
        plan = rest.create_monthly_plan(data["product_id"], PLAN_NAME, PLAN_PRICE, CURRENCY)
        data["plan_id"] = plan.data["id"]
        save_subscription_fixtures(data)
        print(f"Created plan {data['plan_id']} (${PLAN_PRICE} a month).")

    check_subscriptions_match_subscribers(data["subscriptions"])
    done = {entry["seed"] for entry in data["subscriptions"]}
    todo = [(seed, name) for seed, name in enumerate(SUBSCRIBERS, start=1) if seed not in done]
    print(f"{len(done)} of {len(SUBSCRIBERS)} subscriptions already active, {len(todo)} to go.\n")

    for position, (seed, (given, surname)) in enumerate(todo, start=1):
        customer = f"{given} {surname}"
        email = f"{given}.{surname}".lower() + "@example.com"
        created = rest.create_subscription(data["plan_id"], given, surname, email, STORE)
        print(f"[{position}/{len(todo)}] {PLAN_NAME} for {customer}")
        print(f"  subscription {created.subscription_id}: {created.approve_url}")
        webbrowser.open(created.approve_url)
        status = active_when_approved(created.subscription_id)
        if status is None:
            print("  Skipped.\n")
            continue
        data["subscriptions"].append(
            {
                "seed": seed,
                "subscription_id": created.subscription_id,
                "plan_id": data["plan_id"],
                "status": status,
                "customer_name": customer,
                "customer_email": email,
                "plan": PLAN_NAME,
            }
        )
        save_subscription_fixtures(data)
        print(f"  Active: {created.subscription_id}\n")

    rel = SUBSCRIPTION_FIXTURES.relative_to(ROOT).as_posix()
    print(f"Subscriptions done. {len(data['subscriptions'])} active subscriptions in {rel}.")


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")


def main() -> None:
    """Seed the orders, then the subscriptions, in one sitting."""
    print("Each approval page opens in your default browser; it must be logged in as the sandbox buyer.\n")
    seed_orders()
    seed_subscriptions()


if __name__ == "__main__":
    main()
