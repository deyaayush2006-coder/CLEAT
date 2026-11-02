# Architecture

## Request flow

1. **Inbox** (`views/inbox.py`) passes a customer email to `run_agent` (`cleat/agent/support_agent.py`).
2. **Injection check** (`cleat/firewall/injection.py`) rates the raw email before the agent sees it: a Gemini classifier plus regex heuristics. A heuristic hit lifts the rating to at least medium.
3. **Agent loop**: Gemini with tools bound, at most 8 model turns. Every tool the model can call is a *guarded* copy made by `Firewall.guard` (`cleat/firewall/interceptor.py`); a tool name the model invents is routed to the firewall and blocked.
4. **Facts** (`cleat/firewall/facts.py`): for a refund, the capture's amount and status come from Payments v2, and earlier refunds come from the parent order in Orders v2. The 24-hour refund total comes from Cleat's own records. A PayPal failure becomes a `verification_error` fact.
5. **Decision** (`cleat/firewall/engine.py`): pure Python. Hard rules first (unverified facts, non-refundable status, over-refund), then unknown tools are blocked, then the most restrictive matching policy rule wins, otherwise the tier default (read and write allow, money and destructive approve).
6. **Outcome**: allow runs the raw tool once; approve stores a frozen request with its SHA-256 hash; block returns a reason. Every attempt is written to the audit log (`cleat/store/db.py`).
7. **Approvals** (`cleat/firewall/approvals.py`): approving verifies the hash, re-gathers facts from PayPal, re-runs the hard rules and executes the stored arguments. Approvals expire after 24 hours (also enforced by the hourly Render cron job).

## Modules

| Module | Role |
|---|---|
| `cleat/settings.py` | Environment, sandbox-only guard |
| `cleat/paypal/rest.py` | OAuth token cache, Orders v2, Payments v2 |
| `cleat/paypal/tools.py` | Toolkit tools plus `refund_capture` |
| `cleat/firewall/*` | Tiers, schema, facts, engine, interceptor, approvals, injection, compiler |
| `cleat/agent/*` | Prompt and explicit tool loop |
| `cleat/demo/*` | Scenario templates and the capture pool |
| `cleat/store/db.py` | SQLModel tables on SQLite (local) or Postgres (Render) |
| `cleat/ui/*`, `views/*`, `app.py` | Streamlit interface |

## Hosting

`render.yaml` defines a paid Render web service, a Render Postgres database and an hourly cron job running `python -m scripts.expire_stale_approvals`.
