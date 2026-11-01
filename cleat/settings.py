"""Runtime settings for Cleat, read from the environment (and from .env in development).

Importing this module enforces invariant I-6: Cleat only talks to the PayPal sandbox and
refuses to start unless PAYPAL_ENV is exactly "sandbox".
"""

import os
from pathlib import Path

from dotenv import load_dotenv

APP_NAME = "Cleat"
ROOT = Path(__file__).resolve().parent.parent

# A constant rather than an environment variable, so no configuration can point Cleat at live PayPal.
PAYPAL_BASE_URL = "https://api-m.sandbox.paypal.com"

# Variables already set in the real environment (for example on Render) win over .env.
load_dotenv(ROOT / ".env", override=False)


class SettingsError(RuntimeError):
    """The environment is missing a value Cleat needs, or asks for something unsafe."""


def check_sandbox(paypal_env: str | None) -> None:
    """Raise SettingsError unless PAYPAL_ENV is exactly "sandbox" (invariant I-6)."""
    if paypal_env != "sandbox":
        raise SettingsError(
            f'PAYPAL_ENV must be "sandbox", got {paypal_env!r}. Cleat never calls live PayPal.'
        )


def require(name: str) -> str:
    """Return a required environment variable, or raise SettingsError naming the missing one."""
    value = os.getenv(name, "").strip()
    if not value:
        raise SettingsError(
            f"{name} is not set. Add it to .env (see .env.example) or to the host's environment."
        )
    return value


def _int_setting(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        raise SettingsError(f"{name} must be a whole number, got {raw!r}.") from None


PAYPAL_ENV = os.getenv("PAYPAL_ENV")
check_sandbox(PAYPAL_ENV)

DATABASE_URL = os.getenv("DATABASE_URL", "").strip() or "sqlite:///data/cleat.db"
AGENT_RUNS_PER_HOUR = _int_setting("AGENT_RUNS_PER_HOUR", 40)
