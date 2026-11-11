"""Policies page: compile a plain-English policy into rules, simulate it and save a new version."""

import pandas as pd
import streamlit as st

from cleat.firewall.compiler import PolicyCompileError, compile_policy, simulate
from cleat.firewall.schema import Rule
from cleat.store import db
from cleat.ui.components import empty_state, error_state, friendly_error, money, page_header, rules_table
from cleat.ui.theme import DECISION_LABELS

page_header("Policies", "Write the store's rules in plain English. Gemini drafts them; Cleat validates and applies them deterministically.")

try:
    policy = db.active_policy()
    active = db.active_rules()
except Exception as error:
    error_state(friendly_error(error))
    st.stop()


def signature(rule: Rule) -> str:
    """What a rule does, ignoring its ID and wording, for comparing versions."""
    return rule.model_dump_json(exclude={"id", "description"})


with st.container(border=True):
    st.subheader(f"Active rules (version {policy.id})" if policy else "Active rules")
    if active:
        st.dataframe(pd.DataFrame(rules_table(active)), hide_index=True, width="stretch")
        st.caption("Hard rules always apply first: over-refunds, non-refundable payments, unverifiable facts and unknown tools are blocked.")
    else:
        empty_state("No policy saved. Every action gets its tier's default: reads and writes allowed, money and destructive actions held.")

with st.container(border=True):
    st.subheader("Edit the policy")
    text = st.text_area("Policy, one rule per line", value=policy.source_text if policy else "", height=160)
    if st.button("Compile", type="primary", disabled=not text.strip(), icon=":material/auto_fix_high:"):
        with st.spinner("Gemini is drafting rules; Cleat is validating them..."):
            try:
                from cleat.llm import BUSY_MESSAGE, get_llm, on_retry

                def show_busy(attempt: int, delay: float) -> None:
                    st.toast(f"{BUSY_MESSAGE} (attempt {attempt + 1}, waiting {delay:.0f} s)")

                with on_retry(show_busy):
                    st.session_state["draft_rules"] = compile_policy(text, get_llm())
                st.session_state["draft_text"] = text
                st.session_state.pop("compile_errors", None)
            except PolicyCompileError as error:
                st.session_state["compile_errors"] = error.errors
                st.session_state.pop("draft_rules", None)
            except Exception as error:
                st.session_state["compile_errors"] = [friendly_error(error)]
                st.session_state.pop("draft_rules", None)

    if errors := st.session_state.get("compile_errors"):
        st.error("The draft was rejected, so nothing changed:\n\n" + "\n".join(f"- {e}" for e in errors))

    draft: list[Rule] | None = st.session_state.get("draft_rules")
    if draft:
        current = {signature(rule) for rule in active}
        proposed = {signature(rule) for rule in draft}
        rows = rules_table(draft)
        for row, rule in zip(rows, draft):
            row["Change"] = "unchanged" if signature(rule) in current else "new"
        removed = [rule for rule in active if signature(rule) not in proposed]
        rows += [{**row, "Change": "removed"} for row in rules_table(removed)]
        st.markdown("**Compiled preview, compared with the active rules**")
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

        simulate_col, save_col, _ = st.columns([1, 1, 3])
        if simulate_col.button("Simulate on last 20 actions", icon=":material/science:"):
            st.session_state["simulation"] = simulate(draft, last_n=20)
        if save_col.button("Save as new version", icon=":material/save:"):
            saved = db.save_policy(st.session_state.get("draft_text", text), draft)
            for key in ("draft_rules", "draft_text", "simulation"):
                st.session_state.pop(key, None)
            st.success(f"Saved as version {saved.id}. New agent runs use it immediately.")
            st.rerun()

        if (simulation := st.session_state.get("simulation")) is not None:
            if not simulation:
                st.caption("No past actions to simulate yet.")
            else:
                changed = sum(row["changed"] for row in simulation)
                st.markdown(f"**Simulation: {changed} of {len(simulation)} recent decisions would change**")
                st.dataframe(
                    pd.DataFrame(
                        {
                            "Action": row["attempt_id"],
                            "Tool": row["tool"],
                            "Amount": money(row["amount"]),
                            "Before": DECISION_LABELS[row["before"]],
                            "After": DECISION_LABELS[row["after"]],
                            "Changed": "yes" if row["changed"] else "",
                        }
                        for row in simulation
                    ),
                    hide_index=True,
                    width="stretch",
                )

with st.container(border=True):
    st.subheader("Version history")
    history = db.policy_history()
    if not history:
        st.caption("No versions saved yet.")
    for version in history:
        label = " (active)" if version.active else ""
        with st.expander(f"Version {version.id}{label}, saved {version.created_at:%Y-%m-%d %H:%M} UTC"):
            st.text(version.source_text)
