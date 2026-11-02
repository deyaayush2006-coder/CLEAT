"""Approvals page: review actions held by the firewall and approve or reject them."""

import json

import streamlit as st

from cleat.firewall import approvals
from cleat.store import db
from cleat.ui.components import (
    ago,
    empty_state,
    error_state,
    friendly_error,
    money,
    page_header,
    parse_json,
    paypal_ref,
    status_badge,
)

page_header("Approvals", "Actions the firewall held for a human. Approve to execute them in the sandbox, or reject.")
st.caption("Cleat executes the frozen request itself, after checking its SHA-256 hash: the agent cannot change it.")


def summary(tool: str, args: dict) -> str:
    """One line describing the held action."""
    if tool == "refund_capture":
        return f"Refund {money(float(args.get('amount', 0)))} on capture {args.get('capture_id')}"
    if tool == "cancel_subscription":
        return f"Cancel subscription {args.get('subscription_id')}"
    return tool


def decide(approval_id: str, approve: bool) -> None:
    """Approve or reject one held action and remember the outcome to show after the rerun."""
    note = st.session_state.get(f"note-{approval_id}", "")
    try:
        if approve:
            with st.spinner("Re-checking with PayPal and executing the frozen request..."):
                approvals.approve(approval_id, note=note)
        else:
            approvals.deny(approval_id, note=note)
    except approvals.ApprovalError as error:
        st.session_state["approval_message"] = str(error)
    except Exception as error:
        st.session_state["approval_message"] = friendly_error(error)


if message := st.session_state.pop("approval_message", None):
    st.error(message)

try:
    # Expire on view so stale requests never sit in the queue; the hosted demo has no cron.
    approvals.expire_older_than()
    pending = db.pending_approvals()
    decided = [(a, t) for a, t in db.approvals(limit=15) if a.status != "pending"]
except Exception as error:
    error_state(friendly_error(error))
    st.stop()

st.subheader(f"Waiting for you ({len(pending)})")
if not pending:
    empty_state("No held actions: the agent is within policy.")
for approval, attempt in pending:
    args = json.loads(approval.args_json)
    facts = json.loads(attempt.facts_json)
    with st.container(border=True):
        st.markdown(f"**{summary(approval.tool, args)}**")
        st.caption(f"Customer: {attempt.customer or 'unknown'} · held {ago(approval.created_at)} · id `{approval.id}`")
        st.markdown(f"**Why it was held** ({attempt.rule_id or 'tier default'}): {attempt.reason}")
        if "captured_amount" in facts:
            cols = st.columns(4)
            cols[0].metric("Customer paid", money(facts.get("captured_amount")))
            cols[1].metric("Still refundable", money(facts.get("remaining_refundable")))
            cols[2].metric("Refunded in 24 h", money(facts.get("window_total_24h")))
            cols[3].metric("Injection risk", facts.get("inbound_risk", "-"))
            st.caption(f"Verified with PayPal when held. Capture status: {facts.get('capture_status')}. It is checked again on approval.")
        st.text_input("Note (optional)", key=f"note-{approval.id}")
        approve_col, reject_col, _ = st.columns([1, 1, 4])
        approve_col.button("Approve", key=f"approve-{approval.id}", type="primary",
                           on_click=decide, args=(approval.id, True), icon=":material/check:")
        reject_col.button("Reject", key=f"reject-{approval.id}",
                          on_click=decide, args=(approval.id, False), icon=":material/close:")

st.subheader("Recently decided")
if not decided:
    st.caption("Nothing decided yet.")
for approval, attempt in decided:
    args = json.loads(approval.args_json)
    with st.container(border=True):
        text, badge = st.columns([4, 1])
        text.markdown(f"**{summary(approval.tool, args)}** · {attempt.customer or 'unknown'}")
        with badge:
            status_badge(approval.status)
        if approval.note:
            st.caption(f"Note: {approval.note}")
        result = parse_json(approval.result_json)
        if isinstance(result, dict) and result.get("refund_id"):
            paypal_ref("Refund", result["refund_id"])
            st.caption(f"PayPal refund status: **{result.get('status')}**")
            paypal_ref("PayPal-Request-Id", result.get("paypal_request_id"))
            paypal_ref("PayPal debug ID", result.get("paypal_debug_id"))
        elif result:
            st.write(result)
