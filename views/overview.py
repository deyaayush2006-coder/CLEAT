"""Overview page: decision metrics, recent decisions and the demo-data reset."""

import os

import pandas as pd
import streamlit as st

from cleat.firewall.compiler import seed_default_policy
from cleat.store import db
from cleat.ui.components import empty_state, error_state, friendly_error, money, page_header
from cleat.ui.theme import DECISION_COLOURS, DECISION_LABELS

page_header("Overview", "What the firewall has decided on every PayPal action the support agent tried.")
if os.getenv("RENDER"):
    st.caption("Hosted demo: the first load can take a moment.")

try:
    attempts = db.attempts()
except Exception as error:
    error_state(friendly_error(error))
    st.stop()

# Money the firewall kept in the store: refunds it blocked plus held refunds a human rejected.
protected = sum(a.amount or 0.0 for a in attempts if a.tier == "money" and (a.decision == "block" or a.status == "denied"))
counts = {action: sum(1 for a in attempts if a.decision == action) for action in DECISION_LABELS}
tiles = st.columns(5)
tiles[0].metric("Actions evaluated", len(attempts))
tiles[1].metric("Allowed", counts["allow"])
tiles[2].metric("Held", counts["approve"])
tiles[3].metric("Blocked", counts["block"])
tiles[4].metric("$ protected", money(protected))

if not attempts:
    empty_state("No decisions yet. Open **Inbox**, pick scenario 03, and click Run agent.")
else:
    with st.container(border=True):
        st.subheader("Decisions over time")
        frame = pd.DataFrame(
            {"Day": a.created_at.date(), "Decision": DECISION_LABELS[a.decision]} for a in attempts
        )
        by_day = frame.groupby(["Day", "Decision"]).size().unstack(fill_value=0).sort_index()
        # Text labels make each day a full-width bar; a date axis draws a single day as a hairline.
        by_day.index = [day.strftime("%d %b") for day in by_day.index]
        columns = [label for label in DECISION_LABELS.values() if label in by_day.columns]
        st.bar_chart(
            by_day[columns],
            color=[DECISION_COLOURS[action] for action, label in DECISION_LABELS.items() if label in columns],
            height=240,
        )

    with st.container(border=True):
        st.subheader("Last 10 decisions")
        st.caption("Select a row to open that agent run in the Inbox.")
        latest = attempts[:10]
        table = pd.DataFrame(
            {
                "Time": a.created_at.strftime("%Y-%m-%d %H:%M UTC"),
                "Customer": a.customer or "-",
                "Action": a.tool,
                "Amount": money(a.amount),
                "Decision": DECISION_LABELS[a.decision],
                "Outcome": a.status.capitalize(),
                "Reason": a.reason,
            }
            for a in latest
        )
        picked = st.dataframe(table, hide_index=True, on_select="rerun", selection_mode="single-row", width="stretch")
        if picked.selection.rows:
            st.session_state["run_id"] = latest[picked.selection.rows[0]].session_id
            st.switch_page("views/inbox.py")

with st.popover("Reset demo data", icon=":material/restart_alt:"):
    st.write("Deletes Cleat's local records (decisions, approvals, runs, saved policies) and restores the default policy. Nothing is sent to PayPal.")
    if st.button("Reset now", type="primary"):
        db.reset()
        seed_default_policy()
        st.session_state.pop("run_id", None)
        st.rerun()
