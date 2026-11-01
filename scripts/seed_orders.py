"""Creates sandbox orders for the demo store, waits for manual buyer approval,
captures them and records the IDs in data/fixtures/orders.json.

Run from the repo root:  python -m scripts.seed_orders
Log in to https://www.sandbox.paypal.com as your sandbox Personal (buyer) account first.
Orders already in the fixture file are skipped, so the script can be stopped and rerun.
"""

import json
import webbrowser

from cleat.paypal import rest
from cleat.settings import ROOT

STORE = "Kolkata Handloom Co."
CURRENCY = "USD"
FIXTURES = ROOT / "data" / "fixtures" / "orders.json"

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
]


def load_fixtures() -> list[dict]:
    """Return the captured orders recorded so far."""
    return json.loads(FIXTURES.read_text(encoding="utf-8")) if FIXTURES.exists() else []


def save_fixtures(entries: list[dict]) -> None:
    """Write the fixture file; called after every capture so an interruption loses nothing."""
    FIXTURES.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8", newline="\n")


def capture_when_approved(order_id: str) -> rest.CapturedOrder | None:
    """Prompt until the buyer has approved the order, then capture it. Returns None if skipped."""
    while True:
        answer = input("  Approve it in the browser, then press Enter (s = skip, q = quit): ").strip().lower()
        if answer == "q":
            raise SystemExit("Stopped. Run the script again to continue where you left off.")
        if answer == "s":
            return None
        try:
            return rest.capture_order(order_id)
        except rest.PayPalError as e:
            if e.issue != "ORDER_NOT_APPROVED":
                raise
            print("  PayPal says this order is not approved yet.")


def main() -> None:
    """Create, approve (by hand) and capture every catalogue order not yet in the fixtures."""
    entries = load_fixtures()
    done = {entry["seed"] for entry in entries}
    todo = [(seed, row) for seed, row in enumerate(CATALOGUE, start=1) if seed not in done]
    print(f"{len(done)} of {len(CATALOGUE)} orders already captured, {len(todo)} to go.")
    print("Each approval page opens in your default browser; it must be logged in as the sandbox buyer.\n")

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

    print(f"Done. {len(entries)} captured orders in {FIXTURES.relative_to(ROOT).as_posix()}.")


if __name__ == "__main__":
    main()
