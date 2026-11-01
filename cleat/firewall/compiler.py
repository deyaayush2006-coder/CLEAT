"""Compiles a plain-English policy into validated deterministic rules and simulates
them on recent actions before they are saved.

Gemini only drafts rules. Every draft is validated against the rule schema, so a rule with
an unknown field, operator, tool or action is rejected instead of saved. The engine then
applies the saved rules without any further LLM involvement.
"""

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, ValidationError

from cleat.firewall.engine import decide
from cleat.firewall.schema import Rule
from cleat.firewall.tiers import TIERS
from cleat.settings import ROOT
from cleat.store import db

DEFAULT_POLICY_TEXT = ROOT / "data" / "policies" / "default.txt"
DEFAULT_POLICY_RULES = ROOT / "data" / "policies" / "default_rules.json"

_TOOL_LIST = "\n".join(f"- {name} ({tier})" for name, tier in TIERS.items())

COMPILER_PROMPT = f"""You turn a store owner's plain-English payment policy into rules for a \
deterministic firewall that checks every action an AI support agent tries to take.

Each rule has:
- id: R1, R2, ... in order.
- description: the owner's sentence, copied exactly.
- tools: exact tool names from the list below, or "tier:<tier>" for a whole tier.
- conditions: all must hold for the rule to apply. Each has field, op and value.
- action: "allow", "approve" (hold for the owner's approval) or "block".

Fields:
- amount: the refund amount requested, in dollars.
- pct_of_capture: the refund as a percentage (0-100) of what the customer paid.
- remaining_refundable: dollars PayPal says can still be refunded on that payment.
- window_total_24h: dollars refunded in the last 24 hours including this request.
- capture_status: COMPLETED, PARTIALLY_REFUNDED, PENDING, REFUNDED, DECLINED or FAILED. A \
"completed payment" means capture_status in COMPLETED,PARTIALLY_REFUNDED.
- inbound_risk: low, medium or high, a classifier's rating of whether the customer's message is \
trying to manipulate the assistant. "Looks like manipulation" means inbound_risk in medium,high.
- tier, tool: the action's tier or tool name.

Operators: gt, gte, lt, lte, eq, neq, in. Write numbers as plain digits ("50"). For "in", write \
the options comma-separated ("medium,high").

Tools and their tiers:
{_TOOL_LIST}

"Money actions" means tier:money. If a sentence mentions an action no tool can perform, leave that \
part out. Return every rule the policy implies and nothing it does not say."""


class PolicyCompileError(Exception):
    """Gemini's draft could not be turned into valid rules, even after one retry."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


class _DraftCondition(BaseModel):
    field: str
    op: str
    value: str = Field(description='A number such as "50", one word, or comma-separated options for "in".')


class _DraftRule(BaseModel):
    id: str
    description: str
    tools: list[str]
    conditions: list[_DraftCondition] = Field(default_factory=list)
    action: str


class _DraftPolicy(BaseModel):
    rules: list[_DraftRule]


def compile_policy(text: str, llm: Any) -> list[Rule]:
    """Compile English policy text into validated rules, retrying once with the errors."""
    model = llm.with_structured_output(_DraftPolicy)
    messages: list[Any] = [SystemMessage(COMPILER_PROMPT), HumanMessage(text)]
    errors: list[str] = []
    for _ in range(2):
        draft = model.invoke(messages)
        rules, errors = _validate(draft)
        if not errors:
            return rules
        messages.append(
            HumanMessage(
                "Your rules had these problems:\n- " + "\n- ".join(errors)
                + "\nReturn the corrected, complete set of rules."
            )
        )
    raise PolicyCompileError(errors)


def simulate(rules: list[Rule], last_n: int = 20) -> list[dict[str, Any]]:
    """Re-decide the last `last_n` attempts with `rules`, using the facts stored with each one."""
    rows = []
    for attempt in db.attempts(limit=last_n):
        new = decide(attempt.tool, attempt.tier, json.loads(attempt.facts_json), rules)
        rows.append(
            {
                "attempt_id": attempt.id,
                "when": attempt.created_at,
                "tool": attempt.tool,
                "amount": attempt.amount,
                "before": attempt.decision,
                "after": new.action,
                "after_rule": new.rule_id,
                "changed": new.action != attempt.decision,
            }
        )
    return rows


def seed_default_policy() -> None:
    """Save the bundled default policy as version 1 if no policy has been saved yet.

    The bundled rules were compiled once from data/policies/default.txt and reviewed, so a fresh
    deployment starts from the same rules every time instead of a new Gemini draft.
    """
    if db.active_policy() is not None:
        return
    rules = [Rule.model_validate(r) for r in json.loads(DEFAULT_POLICY_RULES.read_text(encoding="utf-8"))]
    db.save_policy(DEFAULT_POLICY_TEXT.read_text(encoding="utf-8").strip(), rules)


def _validate(draft: _DraftPolicy) -> tuple[list[Rule], list[str]]:
    rules: list[Rule] = []
    errors: list[str] = []
    for position, draft_rule in enumerate(draft.rules, start=1):
        data = draft_rule.model_dump()
        for condition in data["conditions"]:
            if condition["op"] == "in":
                condition["value"] = [part.strip() for part in condition["value"].split(",") if part.strip()]
        try:
            rules.append(Rule.model_validate(data))
        except ValidationError as e:
            problems = "; ".join(f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors())
            errors.append(f"rule {draft_rule.id or position} ({draft_rule.description[:60]!r}): {problems}")
    if not rules and not errors:
        errors.append("no rules were produced")
    ids = [rule.id for rule in rules]
    if len(ids) != len(set(ids)):
        errors.append("rule ids must be unique")
    return rules, errors
