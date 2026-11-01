"""Pydantic models for policy rules, their conditions and firewall decisions."""

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from cleat.firewall.tiers import TIERS, Action

FactField = Literal[
    "amount", "pct_of_capture", "remaining_refundable", "capture_status",
    "inbound_risk", "window_total_24h", "tier", "tool",
]
Op = Literal["gt", "gte", "lt", "lte", "eq", "neq", "in"]

NUMERIC_FIELDS = frozenset({"amount", "pct_of_capture", "remaining_refundable", "window_total_24h"})
ORDERED_OPS = frozenset({"gt", "gte", "lt", "lte"})
# Risk levels compare by severity, so "inbound_risk gte medium" means medium or high.
RISK_LEVELS = {"low": 0, "medium": 1, "high": 2}
TIER_NAMES = frozenset({"read", "write", "money", "destructive", "unknown"})
# capture_status values from PayPal's Payments v2 OpenAPI spec. Text fields only accept known
# values, so a compiler typo such as "COMPLETE" is rejected instead of silently never matching.
CAPTURE_STATUSES = frozenset({"COMPLETED", "DECLINED", "PARTIALLY_REFUNDED", "PENDING", "REFUNDED", "FAILED"})
_KNOWN_VALUES = {
    "inbound_risk": frozenset(RISK_LEVELS),
    "capture_status": frozenset(s.lower() for s in CAPTURE_STATUSES),
    "tier": TIER_NAMES,
    "tool": frozenset(TIERS),
}


class Condition(BaseModel):
    """One test against a fact, for example `amount gt 50`."""

    field: FactField
    op: Op
    value: float | str | list[str]

    @model_validator(mode="after")
    def _check_value_fits(self) -> "Condition":
        if self.op == "in" and (not isinstance(self.value, list) or not self.value):
            raise ValueError(f"'in' needs a non-empty list of values, got {self.value!r}")
        if self.op != "in" and isinstance(self.value, list):
            raise ValueError(f"'{self.op}' compares against one value, not a list")
        values = self.value if isinstance(self.value, list) else [self.value]
        if self.field in NUMERIC_FIELDS:
            try:
                numbers = [float(v) for v in values]
            except (TypeError, ValueError):
                raise ValueError(f"{self.field} is a number, got {self.value!r}") from None
            self.value = numbers if self.op == "in" else numbers[0]
            return self
        if self.op in ORDERED_OPS and self.field != "inbound_risk":
            raise ValueError(f"{self.field} cannot be compared with '{self.op}'")
        unknown = [v for v in values if _norm(v) not in _KNOWN_VALUES[self.field]]
        if unknown:
            raise ValueError(f"{self.field} cannot be {unknown}; expected one of {sorted(_KNOWN_VALUES[self.field])}")
        return self

    def holds(self, facts: dict[str, Any]) -> bool:
        """Return True when the fact exists and passes the test. A missing fact never matches."""
        actual = facts.get(self.field)
        if actual is None:
            return False
        if self.op == "in":
            return _norm(actual) in {_norm(v) for v in self.value}
        if self.op in ("eq", "neq"):
            equal = _same(self.field, actual, self.value)
            return equal if self.op == "eq" else not equal
        left, right = _rank(self.field, actual), _rank(self.field, self.value)
        if left is None or right is None:
            return False
        return {"gt": left > right, "gte": left >= right, "lt": left < right, "lte": left <= right}[self.op]


class Rule(BaseModel):
    """A policy rule: when every condition holds for one of its tools, take its action."""

    id: str = Field(min_length=1, max_length=40)
    description: str = Field(min_length=1, description="The plain-English sentence the rule came from.")
    tools: list[str] = Field(min_length=1, description='Tool names, or "tier:<tier>" for a whole tier.')
    conditions: list[Condition] = Field(default_factory=list)
    action: Action

    @model_validator(mode="after")
    def _check_tools_exist(self) -> "Rule":
        for entry in self.tools:
            if entry.startswith("tier:"):
                if entry[len("tier:"):] not in TIER_NAMES:
                    raise ValueError(f"Unknown tier {entry!r}")
            elif entry not in TIERS:
                raise ValueError(f"Unknown tool {entry!r}")
        return self

    def applies_to(self, tool: str, tier: str) -> bool:
        """Return True if the rule names this tool or its tier."""
        return tool in self.tools or f"tier:{tier}" in self.tools


class Decision(BaseModel):
    """The firewall's verdict on one attempted tool call, with the facts it was based on."""

    action: Action
    reason: str
    rule_id: str | None = None
    facts: dict[str, Any] = Field(default_factory=dict)
    approval_id: str | None = None


def _norm(value: Any) -> str:
    return str(value).strip().lower()


def _rank(field: str, value: Any) -> float | None:
    if field == "inbound_risk":
        return RISK_LEVELS.get(_norm(value))
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _same(field: str, left: Any, right: Any) -> bool:
    if field in NUMERIC_FIELDS:
        a, b = _rank(field, left), _rank(field, right)
        return a is not None and b is not None and abs(a - b) < 1e-9
    return _norm(left) == _norm(right)
