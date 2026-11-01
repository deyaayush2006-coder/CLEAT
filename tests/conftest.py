"""Test setup shared by every test module."""

import os

# cleat.settings refuses to import unless PAYPAL_ENV is "sandbox". setdefault keeps any value
# already in the environment, so a shell that says otherwise still fails loudly.
os.environ.setdefault("PAYPAL_ENV", "sandbox")
