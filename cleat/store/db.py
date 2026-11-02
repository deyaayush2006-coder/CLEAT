"""SQLModel storage for attempts, approvals, policy versions and agent runs on
DATABASE_URL (SQLite locally, Postgres when hosted).

All timestamps are timezone-aware UTC; SQLModel stores them that way on both databases.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, Session, SQLModel, col, create_engine, select

from cleat.firewall.schema import Rule
from cleat.settings import DATABASE_URL, ROOT


# Streamlit re-imports edited modules while it runs; without this the tables would be
# declared twice on the shared metadata and the app would fail to load.
_REDEFINABLE = {"extend_existing": True}


def utcnow() -> datetime:
    """Return the current time in UTC."""
    return datetime.now(UTC)


class Attempt(SQLModel, table=True):
    """One tool call the agent tried, the firewall's decision and what happened next."""

    __table_args__ = _REDEFINABLE

    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=utcnow, index=True)
    session_id: str = Field(index=True)
    customer: str | None = None
    tool: str
    tier: str
    args_json: str
    decision: str
    reason: str
    rule_id: str | None = None
    facts_json: str
    amount: float | None = None
    # executed, failed, held, blocked, denied or expired
    status: str
    result_json: str | None = None
    executed_at: datetime | None = None
    approval_id: str | None = None


class Approval(SQLModel, table=True):
    """A held action waiting for a human, with its frozen arguments and their hash."""

    __table_args__ = _REDEFINABLE

    id: str = Field(primary_key=True)
    attempt_id: int = Field(foreign_key="attempt.id")
    created_at: datetime = Field(default_factory=utcnow, index=True)
    tool: str
    args_json: str
    args_hash: str
    # pending, executed, failed, denied or expired
    status: str = "pending"
    decided_at: datetime | None = None
    note: str = ""
    result_json: str | None = None


class PolicySet(SQLModel, table=True):
    """One saved version of the policy: the English text and the rules compiled from it."""

    __table_args__ = _REDEFINABLE

    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=utcnow)
    source_text: str
    rules_json: str
    active: bool = True


class AgentRun(SQLModel, table=True):
    """One agent run on a customer message, kept so the Inbox can show it again."""

    __table_args__ = _REDEFINABLE

    id: str = Field(primary_key=True)
    created_at: datetime = Field(default_factory=utcnow, index=True)
    customer: str | None = None
    message: str
    # running, done or error
    status: str = "running"
    injection_json: str | None = None
    trace_json: str | None = None
    reply: str | None = None


_engine: Engine | None = None


def _create_engine(url: str) -> Engine:
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url.removeprefix("postgres://")
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url.removeprefix("postgresql://")
    if not url.startswith("sqlite"):
        return create_engine(url, pool_pre_ping=True)
    if url == "sqlite://":
        # One shared in-memory database, used by the tests.
        return create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    path = Path(url.removeprefix("sqlite:///"))
    # A relative path is relative to the repo root, not to wherever the process started.
    if not path.is_absolute():
        path = ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{path.as_posix()}", connect_args={"check_same_thread": False})


def get_engine() -> Engine:
    """Return the engine for DATABASE_URL, creating its tables on first use."""
    global _engine
    if _engine is None:
        _engine = _create_engine(DATABASE_URL)
        SQLModel.metadata.create_all(_engine)
    return _engine


def use_database(url: str) -> None:
    """Point storage at another database and create its tables (used by the tests)."""
    global _engine
    _engine = _create_engine(url)
    SQLModel.metadata.create_all(_engine)


def reset() -> None:
    """Delete every stored row by recreating the tables. Never touches PayPal."""
    engine = get_engine()
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)


def _session() -> Session:
    return Session(get_engine(), expire_on_commit=False)


def _save(row: SQLModel) -> Any:
    with _session() as session:
        session.add(row)
        session.commit()
        session.refresh(row)
        return row


# Attempts

def log_attempt(**fields: Any) -> Attempt:
    """Store a new attempt and return it with its ID."""
    return _save(Attempt(**fields))


def update_attempt(attempt_id: int, **fields: Any) -> Attempt:
    """Update fields on an attempt and return it."""
    with _session() as session:
        attempt = session.get(Attempt, attempt_id)
        if attempt is None:
            raise KeyError(f"No attempt {attempt_id}")
        for name, value in fields.items():
            setattr(attempt, name, value)
        session.add(attempt)
        session.commit()
        session.refresh(attempt)
        return attempt


def get_attempt(attempt_id: int) -> Attempt | None:
    """Return one attempt, or None."""
    with _session() as session:
        return session.get(Attempt, attempt_id)


def attempts(limit: int | None = None, session_id: str | None = None) -> list[Attempt]:
    """Return attempts, newest first."""
    with _session() as session:
        query = select(Attempt).order_by(col(Attempt.id).desc())
        if session_id is not None:
            query = query.where(Attempt.session_id == session_id)
        if limit is not None:
            query = query.limit(limit)
        return list(session.exec(query))


def refunded_last_24h() -> float:
    """Total refunded through Cleat in the last 24 hours, from executed refund_capture calls."""
    since = utcnow() - timedelta(hours=24)
    with _session() as session:
        rows = session.exec(
            select(Attempt.amount).where(
                Attempt.tool == "refund_capture",
                Attempt.status == "executed",
                col(Attempt.executed_at) >= since,
            )
        )
        return round(sum(amount or 0.0 for amount in rows), 2)


def refunded_by_capture() -> dict[str, float]:
    """Total refunded through Cleat per capture ID, used to estimate remaining balances."""
    totals: dict[str, float] = {}
    with _session() as session:
        rows = session.exec(
            select(Attempt).where(Attempt.tool == "refund_capture", Attempt.status == "executed")
        )
        for attempt in rows:
            capture_id = json.loads(attempt.args_json).get("capture_id")
            if capture_id:
                totals[capture_id] = round(totals.get(capture_id, 0.0) + (attempt.amount or 0.0), 2)
    return totals


# Approvals

def subscriptions_in_use() -> set[str]:
    """Subscription IDs with a cancellation that Cleat executed or is holding for approval."""
    with _session() as session:
        rows = session.exec(
            select(Attempt.args_json).where(
                Attempt.tool == "cancel_subscription",
                col(Attempt.status).in_(["executed", "held"]),
            )
        )
        ids = set()
        for args_json in rows:
            try:
                ids.add(str(json.loads(args_json)["subscription_id"]))
            except (ValueError, KeyError, TypeError):
                continue
        return ids


def create_approval(**fields: Any) -> Approval:
    """Store a new pending approval."""
    return _save(Approval(**fields))


def get_approval(approval_id: str) -> Approval | None:
    """Return one approval, or None."""
    with _session() as session:
        return session.get(Approval, approval_id)


def update_approval(approval_id: str, **fields: Any) -> Approval:
    """Update fields on an approval and return it."""
    with _session() as session:
        approval = session.get(Approval, approval_id)
        if approval is None:
            raise KeyError(f"No approval {approval_id}")
        for name, value in fields.items():
            setattr(approval, name, value)
        session.add(approval)
        session.commit()
        session.refresh(approval)
        return approval


def approvals(status: str | None = None, limit: int | None = None) -> list[tuple[Approval, Attempt]]:
    """Return approvals with their attempts, newest first, optionally filtered by status."""
    with _session() as session:
        query = select(Approval, Attempt).where(Approval.attempt_id == Attempt.id)
        if status is not None:
            query = query.where(Approval.status == status)
        query = query.order_by(col(Approval.created_at).desc())
        if limit is not None:
            query = query.limit(limit)
        return [(approval, attempt) for approval, attempt in session.exec(query)]


def pending_approvals() -> list[tuple[Approval, Attempt]]:
    """Return every approval still waiting for a human."""
    return approvals(status="pending")


# Policies

def active_policy() -> PolicySet | None:
    """Return the active policy version, or None if none has been saved."""
    with _session() as session:
        return session.exec(
            select(PolicySet).where(PolicySet.active == True).order_by(col(PolicySet.id).desc())  # noqa: E712
        ).first()


def active_rules() -> list[Rule]:
    """Return the rules of the active policy, or no rules if none has been saved."""
    policy = active_policy()
    return [Rule.model_validate(r) for r in json.loads(policy.rules_json)] if policy else []


def save_policy(source_text: str, rules: list[Rule]) -> PolicySet:
    """Save a new policy version and make it the only active one."""
    with _session() as session:
        for old in session.exec(select(PolicySet).where(PolicySet.active == True)):  # noqa: E712
            old.active = False
            session.add(old)
        policy = PolicySet(
            source_text=source_text,
            rules_json=json.dumps([rule.model_dump(mode="json") for rule in rules]),
        )
        session.add(policy)
        session.commit()
        session.refresh(policy)
        return policy


def policy_history() -> list[PolicySet]:
    """Return every saved policy version, newest first."""
    with _session() as session:
        return list(session.exec(select(PolicySet).order_by(col(PolicySet.id).desc())))


# Agent runs

def start_run(run_id: str, message: str, customer: str | None) -> AgentRun:
    """Record that an agent run has started."""
    return _save(AgentRun(id=run_id, message=message, customer=customer))


def finish_run(run_id: str, **fields: Any) -> AgentRun:
    """Store an agent run's outcome."""
    with _session() as session:
        run = session.get(AgentRun, run_id)
        if run is None:
            raise KeyError(f"No run {run_id}")
        for name, value in fields.items():
            setattr(run, name, value)
        session.add(run)
        session.commit()
        session.refresh(run)
        return run


def get_run(run_id: str) -> AgentRun | None:
    """Return one agent run, or None."""
    with _session() as session:
        return session.get(AgentRun, run_id)


def runs_in_last_hour() -> int:
    """Count agent runs started in the last hour, for the hosted-demo rate limit."""
    return runs_in_last(hours=1)


def runs_in_last(hours: float) -> int:
    """Count agent runs started in the last `hours` hours, for the hosted-demo rate limits."""
    since = utcnow() - timedelta(hours=hours)
    with _session() as session:
        return len(list(session.exec(select(AgentRun.id).where(col(AgentRun.created_at) >= since))))
