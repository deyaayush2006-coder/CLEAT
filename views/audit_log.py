"""Audit Log page: every attempted action, with filters and CSV export."""

import json

import pandas as pd
import streamlit as st

from cleat.store import db
from cleat.ui.components import empty_state, error_state, friendly_error, page_header, parse_json
from cleat.ui.theme import DECISION_LABELS

page_header("Audit Log", "Every PayPal action the agent attempted, the facts behind each decision and the outcome.")

try:
    attempts = db.attempts()
except Exception as error:
    error_state(friendly_error(error))
    st.stop()

if not attempts:
    empty_state("No decisions yet. Open **Inbox**, pick scenario 03, and click Run agent.")
    st.stop()

frame = pd.DataFrame(
    {
        "ID": a.id,
        "Time (UTC)": a.created_at.replace(tzinfo=None),
        "Customer": a.customer or "",
        "Action": a.tool,
        "Tier": a.tier,
        "Decision": DECISION_LABELS[a.decision],
        "Outcome": a.status.capitalize(),
        "Amount": a.amount,
        "Rule": a.rule_id or "tier default",
        "Reason": a.reason,
    }
    for a in attempts
)

filters = st.columns(4)
decisions = filters[0].multiselect("Decision", list(DECISION_LABELS.values()))
tools = filters[1].multiselect("Action", sorted(frame["Action"].unique()))
tiers = filters[2].multiselect("Tier", sorted(frame["Tier"].unique()))
first, last = frame["Time (UTC)"].min().date(), frame["Time (UTC)"].max().date()
dates = filters[3].date_input("Dates", (first, last), min_value=first, max_value=last)

shown = frame
if decisions:
    shown = shown[shown["Decision"].isin(decisions)]
if tools:
    shown = shown[shown["Action"].isin(tools)]
if tiers:
    shown = shown[shown["Tier"].isin(tiers)]
if isinstance(dates, tuple) and len(dates) == 2:
    days = shown["Time (UTC)"].dt.date
    shown = shown[(days >= dates[0]) & (days <= dates[1])]

st.caption(f"{len(shown)} of {len(frame)} actions. Select a row for its facts, arguments and PayPal result.")
picked = st.dataframe(
    shown,
    hide_index=True,
    on_select="rerun",
    selection_mode="single-row",
    width="stretch",
    column_config={"Amount": st.column_config.NumberColumn(format="$%.2f")},
)
st.download_button("Download CSV", shown.to_csv(index=False), file_name="cleat_audit_log.csv",
                   mime="text/csv", icon=":material/download:")

if picked.selection.rows:
    attempt = db.get_attempt(int(shown.iloc[picked.selection.rows[0]]["ID"]))
    with st.expander(f"Action {attempt.id}: {attempt.tool}", expanded=True):
        st.markdown("**Facts the decision was based on**")
        st.json(json.loads(attempt.facts_json))
        st.markdown("**Arguments the agent sent**")
        st.json(json.loads(attempt.args_json))
        st.markdown("**Result**")
        result = parse_json(attempt.result_json)
        if isinstance(result, (dict, list)):
            st.json(result)
        else:
            st.write(result or "Not executed.")
