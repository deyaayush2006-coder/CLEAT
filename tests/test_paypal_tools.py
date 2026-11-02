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


def test_registry_is_the_toolkit_tools_plus_cleats_own(registry: tuple) -> None:
    names = [tool.name for tool in registry]
    assert len(names) == len(set(names))
    assert {"create_order", "capture_order", "get_order_details", "cancel_subscription"} <= set(names)
    assert names[-2:] == ["cancel_subscription", "refund_capture"]
    # Cleat's cancel_subscription replaces the toolkit's, which reports success as plain text.
    assert registry[-2] is tools.cancel_subscription_tool


def test_toolkit_tools_call_the_sandbox(registry: tuple) -> None:
    toolkit_tools = [tool for tool in registry if tool not in (tools.cancel_subscription_tool, tools.refund_capture_tool)]
    assert {tool.paypal_api._paypal_client.base_url for tool in toolkit_tools} == {SANDBOX}


def test_cancel_tool_reports_paypals_status_after_the_call(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fake_cancel(subscription_id: str, reason: str) -> rest.PayPalResponse:
        calls.append((subscription_id, reason))
        return rest.PayPalResponse(data={}, request_id="req-1", debug_id="dbg-1")

    def fake_get(subscription_id: str) -> rest.PayPalResponse:
        return rest.PayPalResponse(data={"id": subscription_id, "status": "CANCELLED"}, request_id=None, debug_id="dbg-2")

    monkeypatch.setattr(rest, "cancel_subscription", fake_cancel)
    monkeypatch.setattr(rest, "get_subscription", fake_get)
    result = json.loads(tools.cancel_subscription_tool.invoke({"subscription_id": "I-SUB1", "reason": "No longer needed"}))
    assert calls == [("I-SUB1", "No longer needed")]
    assert (result["status"], result["paypal_request_id"], result["paypal_debug_id"]) == ("CANCELLED", "req-1", "dbg-1")


def test_cancel_tool_returns_paypal_errors_as_text(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing_cancel(*args: object) -> rest.PayPalResponse:
        raise rest.PayPalError(422, "UNPROCESSABLE_ENTITY", "Invalid status", issue="SUBSCRIPTION_STATUS_INVALID")

    monkeypatch.setattr(rest, "cancel_subscription", failing_cancel)
    result = tools.cancel_subscription_tool.invoke({"subscription_id": "I-SUB1"})
    assert "SUBSCRIPTION_STATUS_INVALID" in result


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
