"""Expires approvals that have been pending for more than 24 hours (for a scheduled job).

Run from the repo root:  python -m scripts.expire_stale_approvals
"""

from cleat.firewall.approvals import expire_older_than


def main() -> None:
    """Expire stale approvals and report how many there were."""
    print(f"Expired {expire_older_than()} approval(s) held for more than 24 hours.")


if __name__ == "__main__":
    main()
