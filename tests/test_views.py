"""Render every page with Streamlit's AppTest, empty and with data, and check it does not error."""

import json
from collections.abc import Callable
from datetime import timedelta

import pytest
from fakes import ScriptedLLM
from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool
from streamlit.testing.v1 import AppTest

from cleat.agent.support_agent import run_agent
from cleat.firewall.compiler import seed_default_policy
from cleat.paypal.tools import RefundCaptureArgs
from cleat.store import db

pytestmark = pytest.mark.usefixtures("memory_db")
PAGES = ["overview", "inbox", "approvals", "audit_log", "policies"]


def page(name: str) -> AppTest:
    return AppTest.from_file(f"../views/{name}.py", default_timeout=60)


def texts(app: AppTest) -> str:
    return " ".join(str(element.value) for element in [*app.markdown, *app.caption, *app.info, *app.warning, *app.error])


def refund_tool() -> StructuredTool:
    return StructuredTool.from_function(
        func=lambda **kwargs: json.dumps({"refund_id": "REF1", "status": "COMPLETED", "paypal_request_id": "req-1"}),
        name="refund_capture", description="Refund a capture.", args_schema=RefundCaptureArgs,
    )


def record_runs(fake_paypal: Callable[..., None]) -> str:
    """Store one agent run with an allowed, a held and a blocked refund; return its session ID."""
    fake_paypal(captured="250.00")
    calls = [
        AIMessage(content="", tool_calls=[{"name": "refund_capture", "args": {"capture_id": "CAP1", "amount": amount}, "id": f"c{i}"}])
        for i, amount in enumerate([20, 180, 300])
    ]
    llm = ScriptedLLM(structured=[{"risk": "low", "evidence": "Ordinary."}], turns=[*calls, AIMessage(content="Thanks!")])
    return run_agent("Please refund me.", llm, [refund_tool()], customer="Priya Sen").session_id


@pytest.fixture
def seeded_policy(memory_db: None) -> None:
    seed_default_policy()


@pytest.mark.usefixtures("seeded_policy")
@pytest.mark.parametrize("name", PAGES)
def test_every_page_renders_empty_with_banner_and_title(name: str) -> None:
    app = page(name).run()
    assert not app.exception, app.exception
    assert app.title and "SANDBOX" in texts(app)


@pytest.mark.usefixtures("seeded_policy")
@pytest.mark.parametrize("name", PAGES)
def test_every_page_renders_with_data(name: str, fake_paypal: Callable[..., None]) -> None:
    session_id = record_runs(fake_paypal)
    app = page(name)
    app.session_state["run_id"] = session_id
    app.run()
    assert not app.exception, app.exception


@pytest.mark.usefixtures("seeded_policy")
def test_overview_counts_each_decision(fake_paypal: Callable[..., None]) -> None:
    record_runs(fake_paypal)
    app = page("overview").run()
    values = {metric.label: metric.value for metric in app.metric}
    assert (values["Actions evaluated"], values["Allowed"], values["Held"], values["Blocked"]) == ("3", "1", "1", "1")
    assert values["$ protected"] == "$300.00"


@pytest.mark.usefixtures("seeded_policy")
def test_inbox_shows_the_stored_run_as_a_timeline(fake_paypal: Callable[..., None]) -> None:
    app = page("inbox")
    app.session_state["run_id"] = record_runs(fake_paypal)
    app.run()
    shown = texts(app)
    assert "Step 3" in shown and "HARD-OVER-REFUND" in shown and "REF1" in shown


@pytest.mark.usefixtures("seeded_policy")
def test_rejecting_a_held_action_from_the_approvals_page(fake_paypal: Callable[..., None]) -> None:
    record_runs(fake_paypal)
    [(approval, _)] = db.pending_approvals()
    app = page("approvals").run()
    app.button(key=f"reject-{approval.id}").click().run()
    assert not app.exception
    assert db.get_approval(approval.id).status == "denied"


@pytest.mark.usefixtures("seeded_policy")
def test_approvals_page_expires_requests_held_over_24_hours(fake_paypal: Callable[..., None]) -> None:
    record_runs(fake_paypal)
    [(approval, _)] = db.pending_approvals()
    db.update_approval(approval.id, created_at=db.utcnow() - timedelta(hours=25))
    app = page("approvals").run()
    assert not app.exception
    assert db.get_approval(approval.id).status == "expired"
    assert app.subheader[0].value == "Waiting for you (0)"


def test_the_app_shell_starts_on_the_overview() -> None:
    app = AppTest.from_file("../app.py", default_timeout=60).run()
    assert not app.exception, app.exception
    assert app.title[0].value == "Overview"


def test_inbox_explains_how_to_seed_when_no_orders_exist(monkeypatch: pytest.MonkeyPatch) -> None:
    from cleat.demo import pool

    monkeypatch.setattr(pool, "seeded_orders", list)
    app = page("inbox").run()
    assert "scripts.seed_orders" in texts(app)
