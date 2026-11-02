"""Runs scripts/seed_orders.py unattended: the sandbox buyer's approvals are clicked by a
headless browser (approve.cjs) instead of by hand. Everything else, including what is
recorded and how a rerun resumes, is the real seed script, unchanged.

Run from the repo root:  python -m tools.sandbox_seeding.auto_seed
Needs PAYPAL_ENV=sandbox, PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET, PAYPAL_SANDBOX_BUYER_EMAIL
and PAYPAL_SANDBOX_BUYER_PASSWORD in the environment, and Node with Playwright.
Stops at the first approval that fails (a screenshot is saved); rerun to resume.
"""

import builtins
import os
import subprocess
import sys
import time
from pathlib import Path

# Makes the calls do nothing where claude-progress is not installed.
_bytecode, sys.dont_write_bytecode = sys.dont_write_bytecode, True  # no __pycache__ in the plugin
try:
    sys.path.insert(0, os.environ["CLAUDE_PROGRESS_DIR"]); from claude_progress import claude_progress
except Exception:
    def claude_progress(*args): pass
finally:
    sys.dont_write_bytecode = _bytecode

from scripts import seed_orders as seed  # noqa: E402

HERE = Path(__file__).resolve().parent
# A subscription can sit at APPROVED for a few seconds before PayPal makes it ACTIVE.
RECHECK_SECONDS = 5
MAX_CHECKS_PER_ITEM = 12


class Approver:
    """Feeds approval links to the headless browser and answers the seed script's prompts."""

    def __init__(self, total: int) -> None:
        self.proc = subprocess.Popen(
            ["node", str(HERE / "approve.cjs")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1,
        )
        self.total = total
        self.done = 0
        self.checks = 0
        claude_progress("-n", "seed-sandbox", f"0/{total}", "logging in as the sandbox buyer")

    def open(self, url: str) -> bool:
        """Stands in for webbrowser.open: approve the link, or stop the run if that fails."""
        self.proc.stdin.write(url + "\n")
        self.proc.stdin.flush()
        answer = self.proc.stdout.readline().strip()
        if not answer.startswith("ok"):
            claude_progress("-n", "seed-sandbox", "fail", answer or "browser helper exited")
            raise SystemExit(f"Approval failed: {answer or 'the browser helper exited'}. Rerun to resume.")
        print("  approved in the browser")
        self.checks = 0
        return True

    def input(self, prompt: str = "") -> str:
        """Stands in for input(): carry on once approved, re-checking a few times if PayPal lags."""
        self.checks += 1
        if self.checks == 1:
            self.done += 1
            claude_progress("-n", "seed-sandbox", f"{self.done}/{self.total}")
            return ""
        if self.checks > MAX_CHECKS_PER_ITEM:
            return "q"  # the seed script saves what it has and stops; a rerun resumes
        time.sleep(RECHECK_SECONDS)
        return ""

    def close(self) -> None:
        self.proc.stdin.close()
        self.proc.wait(timeout=30)


def remaining() -> int:
    orders_done = {e["seed"] for e in seed.load_fixtures()}
    subs_done = {e["seed"] for e in seed.load_subscription_fixtures()["subscriptions"]}
    return (len(seed.CATALOGUE) - len(orders_done)) + (len(seed.SUBSCRIBERS) - len(subs_done))


def main() -> None:
    for name in ("PAYPAL_SANDBOX_BUYER_EMAIL", "PAYPAL_SANDBOX_BUYER_PASSWORD"):
        if not os.getenv(name, "").strip():
            raise SystemExit(f"{name} is not set.")
    total = remaining()
    if total == 0:
        print("Nothing to seed: every order and subscription is already recorded.")
        claude_progress("-n", "seed-sandbox", "done", "nothing left to seed")
        return
    approver = Approver(total)
    seed.webbrowser.open = approver.open
    builtins.input = approver.input
    try:
        seed.main()
    finally:
        approver.close()
    claude_progress("-n", "seed-sandbox", "done", f"{approver.done} approvals")


if __name__ == "__main__":
    main()
