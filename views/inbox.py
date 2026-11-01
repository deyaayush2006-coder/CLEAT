"""Inbox page: run the support agent on a customer email and show each firewall step."""

import json
from typing import Any

import streamlit as st

from cleat.agent.support_agent import RateLimited, run_agent
from cleat.demo.scenarios import NoCaptureAvailable, fill, load_scenarios
from cleat.firewall.injection import InjectionVerdict
from cleat.store import db
from cleat.ui.components import (
    decision_and_status,
    empty_state,
    error_state,
    friendly_error,
    money,
    page_header,
    parse_json,
    paypal_ref,
    risk_badge,
)
from cleat.ui.theme import DECISION_LABELS

page_header("Inbox", "Run the support agent on a customer email and watch the firewall check every PayPal action.")

SCENARIOS = {scenario.id: scenario for scenario in load_scenarios()}


def load_scenario() -> None:
    """Fill the message box from the selected scenario and a suitable seeded sandbox order."""
    scenario = SCENARIOS[st.session_state["scenario_id"]]
    try:
        filled = fill(scenario)
    except NoCaptureAvailable as error:
        st.session_state.update(message="", customer="", fill_error=str(error))
        return
    st.session_state.update(message=filled.message, customer=filled.customer, fill_error=None)


def describe_action(tool: str, args: dict[str, Any]) -> str:
    """Say in words what the agent asked PayPal to do."""
    if tool == "refund_capture":
        reason = f" ({args['reason']})" if args.get("reason") else ""
        return f"Refund {money(float(args.get('amount', 0)))} on capture `{args.get('capture_id')}`{reason}"
    if tool == "get_order_details":
        return f"Look up order `{args.get('order_id')}`"
    details = ", ".join(f"{key}: {value}" for key, value in args.items())
    return f"`{tool}` with {details}" if details else f"`{tool}`"


def show_facts(facts: dict[str, Any]) -> None:
    """Show the facts the decision was based on, PayPal-verified ones first."""
    if "verification_error" in facts:
        st.warning(f"PayPal could not confirm this action: {facts['verification_error']}")
    if "captured_amount" in facts:
        cols = st.columns(4)
        cols[0].metric("Customer paid", money(facts.get("captured_amount")))
        cols[1].metric("Already refunded", money(facts.get("refunded_total")))
        cols[2].metric("Still refundable", money(facts.get("remaining_refundable")))
        cols[3].metric("Refunded in 24 h", money(facts.get("window_total_24h")))
        st.caption(f"Capture status from PayPal: **{facts.get('capture_status')}**. Injection risk: **{facts.get('inbound_risk')}**.")
        paypal_ref("Order", facts.get("order_id"))
        paypal_ref("Capture", facts.get("capture_id"))
        paypal_ref("PayPal debug ID (capture lookup)", facts.get("paypal_debug_id"))
    else:
        st.caption(f"Tier: **{facts.get('tier')}**. Injection risk: **{facts.get('inbound_risk')}**.")


def show_result(result: Any) -> None:
    """Show what PayPal returned for an executed or failed action."""
    if isinstance(result, dict) and result.get("refund_id"):
        paypal_ref("Refund", result["refund_id"])
        st.caption(f"Refund status: **{result.get('status')}**")
        paypal_ref("PayPal-Request-Id", result.get("paypal_request_id"))
        paypal_ref("PayPal debug ID", result.get("paypal_debug_id"))
    elif isinstance(result, dict) and "status" in result:
        st.caption(f"PayPal order status: **{result['status']}**, amount {result.get('amount', '-')}")
    elif result:
        st.write(result)


def show_step(number: int, step: dict[str, Any]) -> None:
    """Show one tool call: what was asked, the facts, the rule matched and the outcome."""
    decision = step["decision"]
    attempt = db.get_attempt(step["attempt_id"])
    status = attempt.status if attempt else step.get("status", "")
    with st.container(border=True):
        st.markdown(f"**Step {number}: proposed PayPal action**")
        decision_and_status(decision["action"], status)
        st.markdown(describe_action(step["tool"], step["args"]))
        st.markdown("**Facts fetched before deciding**")
        show_facts(decision["facts"])
        rule = decision.get("rule_id") or "tier default"
        st.markdown(f"**Rule matched** ({rule}): {decision['reason']}")
        if status in {"executed", "failed"}:
            show_result(parse_json(attempt.result_json if attempt else step.get("result")))
        elif status == "held":
            st.info(f"Held for human approval (id `{decision.get('approval_id')}`). Decide it on the Approvals page.")
        elif status in {"denied", "expired"}:
            st.info(f"This held action was {status}.")
        else:
            st.error(step.get("result", "Blocked."))


def show_run(run_id: str) -> None:
    """Show a stored agent run as a timeline."""
    run = db.get_run(run_id)
    if run is None:
        empty_state("That run is no longer stored. Run a scenario to see a new one.")
        return
    if run.status != "done":
        error_state("This run did not finish. Try running it again.")
        return
    verdict = InjectionVerdict.model_validate_json(run.injection_json)
    steps = json.loads(run.trace_json or "[]")
    with st.container(border=True):
        st.markdown(f"**Customer message** from {run.customer or 'unknown'}")
        risk_badge(verdict.risk)
        st.caption(f"Checked before the agent read it. Evidence: {verdict.evidence}")
        if not verdict.classifier_available:
            st.caption("Gemini classifier was unavailable; the regex heuristics decided alone.")
    if not steps:
        st.caption("The agent did not ask PayPal to do anything.")
    for number, step in enumerate(steps, start=1):
        show_step(number, step)
    with st.container(border=True):
        st.markdown("**Reply sent to the customer**")
        st.markdown(run.reply)
    with st.expander("Technical details"):
        st.json({"run_id": run.id, "injection": verdict.model_dump(), "steps": steps})


left, right = st.columns([2, 3], gap="large")

with left:
    mode = st.radio("Message", ["Demo scenario", "Paste your own ticket"], horizontal=True)
    if mode == "Demo scenario":
        if "scenario_id" not in st.session_state:
            st.session_state["scenario_id"] = next(iter(SCENARIOS))
            load_scenario()
        # A finished run used up refundable balance, so the scenario is refilled from a fresh order.
        elif st.session_state.pop("reload_scenario", False):
            load_scenario()
        st.selectbox(
            "Scenario",
            list(SCENARIOS),
            format_func=lambda sid: f"{sid} · {SCENARIOS[sid].title}",
            key="scenario_id",
            on_change=load_scenario,
        )
        scenario = SCENARIOS[st.session_state["scenario_id"]]
        st.caption(f"Expected: **{DECISION_LABELS[scenario.expected]}**. {scenario.shows}")
        if st.session_state.get("fill_error"):
            st.warning(
                f"{st.session_state['fill_error']} Seed sandbox orders with `python -m scripts.seed_orders`, "
                "or paste your own ticket instead."
            )
            st.button("Try again", on_click=load_scenario)
        message = st.text_area("Customer email", key="message", height=230)
        customer = st.session_state.get("customer") or None
    else:
        customer = st.text_input("Customer name", placeholder="For example Priya Sen") or None
        message = st.text_area("Customer email", height=230, placeholder="Paste a support ticket here.")

    if st.button("Run agent", type="primary", disabled=not message.strip(), icon=":material/play_arrow:"):
        with st.status("Checking the message for prompt injection, then running the agent...", expanded=True) as status:
            try:
                from cleat.llm import get_llm
                from cleat.paypal.tools import raw_tools

                result = run_agent(message, get_llm(), raw_tools(), customer=customer)
            except RateLimited as error:
                status.update(label="Rate limit reached", state="error")
                st.warning(str(error))
            except Exception as error:
                status.update(label="The run failed", state="error")
                error_state(friendly_error(error))
            else:
                # Widgets cannot be refilled after they are drawn, so refill on a fresh rerun.
                st.session_state.update(run_id=result.session_id, reload_scenario=mode == "Demo scenario")
                st.rerun()

with right:
    if st.session_state.get("run_id"):
        show_run(st.session_state["run_id"])
    else:
        empty_state("Pick a scenario or paste a ticket, then press Run agent. Each PayPal action the agent tries appears here.")
