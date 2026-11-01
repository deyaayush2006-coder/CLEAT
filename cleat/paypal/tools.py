"""Registry of raw, unguarded PayPal tools: the PayPal Agent Toolkit tools plus
Cleat's refund_capture tool, which the toolkit does not provide.

Nothing here decides whether a call is allowed. The firewall wraps these tools before
the agent ever sees them.
"""

import json
from functools import cache

from langchain_core.tools import BaseTool, StructuredTool, ToolException
from paypal_agent_toolkit.langchain.toolkit import PayPalToolkit
from paypal_agent_toolkit.shared.configuration import Configuration, Context
from paypal_agent_toolkit.shared.constants import SANDBOX_BASE_URL
from pydantic import BaseModel, Field

from cleat.paypal import rest
from cleat.settings import PAYPAL_BASE_URL, SettingsError, require

# Every action defined by the installed toolkit (1.1.0), copied from
# paypal_agent_toolkit/shared/tools.py. That version has no disputes, shipment-tracking
# or transaction-search tools.
TOOLKIT_ACTIONS: dict[str, dict[str, bool]] = {
    "orders": {"create": True, "get": True, "capture": True},
    "invoices": {
        "create": True,
        "list": True,
        "get": True,
        "send": True,
        "sendReminder": True,
        "cancel": True,
        "generateQRC": True,
    },
    "products": {"create": True, "list": True, "show": True},
    "subscriptionPlans": {"create": True, "list": True, "show": True},
    "subscriptions": {"create": True, "show": True, "cancel": True},
}

# The toolkit picks its own base URL from Context(sandbox=True); refuse to run if that
# ever stops being the sandbox URL Cleat is pinned to (invariant I-6).
if SANDBOX_BASE_URL != PAYPAL_BASE_URL:
    raise SettingsError(f"paypal-agent-toolkit sandbox URL is {SANDBOX_BASE_URL!r}, expected {PAYPAL_BASE_URL!r}")


class RefundCaptureArgs(BaseModel):
    """Arguments for refund_capture."""

    capture_id: str = Field(description="ID of the captured payment to refund.")
    amount: float = Field(gt=0, description="Amount to refund, for example 20.00.")
    currency: str = Field(default="USD", description="Three-letter currency code of the capture.")
    reason: str = Field(default="", max_length=255, description="Short reason, shown to the customer on the refund.")


def _refund_capture(capture_id: str, amount: float, currency: str = "USD", reason: str = "") -> str:
    try:
        resp = rest.refund_capture(capture_id, amount, currency, note=reason)
    except (rest.PayPalError, ValueError) as e:
        # ToolException is returned to the agent as text instead of crashing the run.
        raise ToolException(str(e)) from e
    return json.dumps(
        {
            "refund_id": resp.data.get("id"),
            "status": resp.data.get("status"),
            "amount": resp.data.get("amount"),
            "capture_id": capture_id,
            "paypal_request_id": resp.request_id,
            "paypal_debug_id": resp.debug_id,
        }
    )


refund_capture_tool = StructuredTool.from_function(
    func=_refund_capture,
    name="refund_capture",
    description="Refund all or part of a captured PayPal payment, identified by its capture ID.",
    args_schema=RefundCaptureArgs,
    handle_tool_error=True,
)


@cache
def raw_tools() -> tuple[BaseTool, ...]:
    """Return every raw PayPal tool: the toolkit's tools followed by refund_capture.

    Built once per process. Raises SettingsError if the PayPal credentials are missing.
    """
    toolkit = PayPalToolkit(
        client_id=require("PAYPAL_CLIENT_ID"),
        secret=require("PAYPAL_CLIENT_SECRET"),
        configuration=Configuration(actions=TOOLKIT_ACTIONS, context=Context(sandbox=True)),
    )
    return (*toolkit.get_tools(), refund_capture_tool)
