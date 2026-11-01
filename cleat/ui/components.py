"""Shared Streamlit building blocks: page headers, decision badges, the sandbox banner,
empty and error states and PayPal ID labels.
"""

import json
from datetime import datetime
from typing import Any

import streamlit as st

from cleat.firewall.schema import Rule
from cleat.ui.theme import (
    DECISION_COLOURS,
    DECISION_LABELS,
    NEUTRAL,
    RISK_COLOURS,
    SANDBOX_BANNER_HTML,
    STATUS_COLOURS,
    badge_html,
)


def sandbox_banner() -> None:
    """Show the thin SANDBOX banner every page starts with (invariant I-8)."""
    st.markdown(SANDBOX_BANNER_HTML, unsafe_allow_html=True)


def page_header(title: str, subtitle: str) -> None:
    """Show the sandbox banner, the page title and its one-line purpose."""
    sandbox_banner()
    st.title(title)
    st.caption(subtitle)


def _decision_html(action: str) -> str:
    return badge_html(DECISION_LABELS.get(action, action), DECISION_COLOURS.get(action, NEUTRAL))


def _status_html(status: str) -> str:
    return badge_html(status.capitalize(), STATUS_COLOURS.get(status, NEUTRAL))


def decision_badge(action: str) -> None:
    """Show an Allowed, Held or Blocked badge in the fixed decision colours."""
    st.markdown(_decision_html(action), unsafe_allow_html=True)


def decision_and_status(action: str, status: str) -> None:
    """Show the firewall's decision and what happened next, side by side."""
    st.markdown(f"{_decision_html(action)} &nbsp; {_status_html(status)}", unsafe_allow_html=True)


def risk_badge(risk: str) -> None:
    """Show the injection-risk rating as a badge."""
    st.markdown(badge_html(f"Injection risk: {risk}", RISK_COLOURS.get(risk, NEUTRAL)), unsafe_allow_html=True)


def status_badge(status: str) -> None:
    """Show what happened to an attempt (executed, held, blocked, failed...)."""
    st.markdown(_status_html(status), unsafe_allow_html=True)


def empty_state(message: str) -> None:
    """Show a calm message when a page has nothing to display."""
    st.info(message, icon=":material/inbox:")


def error_state(message: str, retry_label: str | None = None) -> bool:
    """Show a friendly error. Returns True if the optional retry button was pressed."""
    st.error(message, icon=":material/error:")
    return bool(retry_label) and st.button(retry_label)


def paypal_ref(kind: str, paypal_id: str | None) -> None:
    """Show a labelled, monospaced PayPal ID."""
    if paypal_id:
        st.markdown(f"**{kind}** `{paypal_id}`")


def money(amount: float | None) -> str:
    """Format a dollar amount, or a dash when there is none."""
    return "-" if amount is None else f"${amount:,.2f}"


def ago(moment: datetime) -> str:
    """Describe how long ago a UTC time was, for example '5 min ago'."""
    from cleat.store.db import utcnow

    seconds = int((utcnow() - moment).total_seconds())
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60} min ago"
    if seconds < 86400:
        return f"{seconds // 3600} h ago"
    return f"{seconds // 86400} d ago"


_OP_SYMBOLS = {"gt": ">", "gte": "≥", "lt": "<", "lte": "≤", "eq": "=", "neq": "≠", "in": "in"}


def describe_conditions(rule: Rule) -> str:
    """Write a rule's conditions as one readable line, for example 'amount ≤ 50'."""
    if not rule.conditions:
        return "always"

    def show(value: object) -> str:
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value)

    return " and ".join(
        f"{c.field} {_OP_SYMBOLS[c.op]} "
        + (", ".join(show(v) for v in c.value) if isinstance(c.value, list) else show(c.value))
        for c in rule.conditions
    )


def rules_table(rules: list[Rule]) -> list[dict[str, Any]]:
    """Rows for showing rules in st.dataframe."""
    return [
        {
            "Rule": rule.id,
            "Sentence": rule.description,
            "Tools": ", ".join(rule.tools),
            "When": describe_conditions(rule),
            "Action": DECISION_LABELS[rule.action],
        }
        for rule in rules
    ]


def parse_json(text: str | None) -> Any:
    """Parse stored JSON, falling back to the raw text for non-JSON tool output."""
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return text


def friendly_error(error: Exception) -> str:
    """Turn an exception into a message a merchant can act on."""
    from cleat.paypal.rest import PayPalError
    from cleat.settings import SettingsError

    if isinstance(error, SettingsError):
        return f"Cleat is missing configuration: {error}"
    if isinstance(error, PayPalError):
        return f"PayPal is unavailable or refused the request: {error}"
    text = str(error)
    if "503" in text or "UNAVAILABLE" in text or "overloaded" in text.lower():
        return "Gemini is busy right now. Please try again in a minute."
    if "429" in text or "RESOURCE_EXHAUSTED" in text:
        return "The Gemini quota is used up for now. Please try again later."
    return f"Something went wrong: {text[:300]}"
