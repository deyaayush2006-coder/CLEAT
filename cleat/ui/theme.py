"""Cleat's decision colours, defined once, and the only static HTML badges and
banners the UI uses.
"""

import html

DECISION_COLOURS = {"allow": "#15803D", "approve": "#B45309", "block": "#B91C1C"}
DECISION_LABELS = {"allow": "Allowed", "approve": "Held", "block": "Blocked"}
RISK_COLOURS = {"low": DECISION_COLOURS["allow"], "medium": DECISION_COLOURS["approve"], "high": DECISION_COLOURS["block"]}
STATUS_COLOURS = {
    "executed": DECISION_COLOURS["allow"],
    "held": DECISION_COLOURS["approve"],
    "pending": DECISION_COLOURS["approve"],
    "blocked": DECISION_COLOURS["block"],
    "denied": DECISION_COLOURS["block"],
    "failed": DECISION_COLOURS["block"],
}
NEUTRAL = "#475569"

LOGO_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="96" height="28" viewBox="0 0 96 28">'
    '<text x="0" y="22" font-family="sans-serif" font-size="22" font-weight="700" fill="#0F766E">Cleat</text>'
    "</svg>"
)

SANDBOX_BANNER_HTML = (
    '<div style="background:#E2E8F0;color:#0F172A;border-radius:6px;padding:6px 12px;'
    'font-size:0.85rem;margin-bottom:0.5rem;"><strong>SANDBOX</strong> &mdash; no real money moves. '
    "Cleat only talks to api-m.sandbox.paypal.com.</div>"
)


def badge_html(label: str, colour: str) -> str:
    """Return a small static coloured label."""
    return (
        f'<span style="background:{colour};color:#FFFFFF;border-radius:4px;padding:2px 8px;'
        f'font-size:0.8rem;font-weight:600;">{html.escape(label)}</span>'
    )
