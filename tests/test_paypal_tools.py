"""Offline tests for the raw PayPal tool registry in cleat.paypal.tools."""

import json
from collections.abc import Iterator

import pytest
from pydantic import ValidationError

from cleat.paypal import rest, tools

SANDBOX = "https://api-m.sandbox.paypal.com"


@pytest.fixture
def registry(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple]:
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "test-client")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "test-secret")
    tools.raw_tools.cache_clear()
    yield tools.raw_tools()
    tools.raw_tools.cache_clear()


def test_registry_is_the_toolkit_tools_plus_refund_capture(registry: tuple) -> None:
    names = [tool.name for tool in registry]
    assert len(names) == len(set(names))
    assert {"create_order", "capture_order", "get_order_details", "cancel_subscription"} <= set(names)
    assert names[-1] == "refund_capture"


def test_toolkit_tools_call_the_sandbox(registry: tuple) -> None:
    toolkit_tools = [tool for tool in registry if tool.name != "refund_capture"]
    assert {tool.paypal_api._paypal_client.base_url for tool in toolkit_tools} == {SANDBOX}


def test_refund_tool_reports_the_refund_and_trace_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_refund(capture_id: str, amount: float, currency: str, note: str = "") -> rest.PayPalResponse:
        assert (capture_id, amount, currency, note) == ("CAP1", 20.0, "USD", "Torn scarf")
        return rest.PayPalResponse(data={"id": "REF1", "status": "COMPLETED"}, request_id="req-1", debug_id="dbg-1")

    monkeypatch.setattr(rest, "refund_capture", fake_refund)
    result = json.loads(tools.refund_capture_tool.invoke({"capture_id": "CAP1", "amount": 20, "reason": "Torn scarf"}))
    assert result["refund_id"] == "REF1"
    assert (result["paypal_request_id"], result["paypal_debug_id"]) == ("req-1", "dbg-1")


def test_refund_tool_returns_paypal_errors_as_text(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing_refund(*args: object, **kwargs: object) -> rest.PayPalResponse:
        raise rest.PayPalError(422, "UNPROCESSABLE_ENTITY", "Refund exceeds the captured amount", issue="REFUND_AMOUNT_EXCEEDED")

    monkeypatch.setattr(rest, "refund_capture", failing_refund)
    result = tools.refund_capture_tool.invoke({"capture_id": "CAP1", "amount": 500})
    assert "REFUND_AMOUNT_EXCEEDED" in result


def test_refund_tool_rejects_a_non_positive_amount() -> None:
    with pytest.raises(ValidationError):
        tools.refund_capture_tool.invoke({"capture_id": "CAP1", "amount": 0})
