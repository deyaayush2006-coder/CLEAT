# Devpost submission (draft)

**Live demo:** https://cleat-pqyb.onrender.com (free plan: the first load can take about a minute)

**Tagline:** Your AI support agent can be talked into anything. Your PayPal can't.

**Inspiration:** Small merchants are handing support email to AI agents that can issue PayPal refunds. One manipulated message or one inflated claim can move real money, and a system prompt is not a security boundary.

**What it does:** Cleat sits between a support agent and PayPal. Every action the agent attempts is checked against facts fetched from PayPal (capture amount, status, refund history), decided by a deterministic policy engine, and allowed, held for a human, or blocked, with every attempt logged. Customer messages are rated for prompt injection before the agent reads them. Held refunds and subscription cancellations are executed by Cleat from a hashed, frozen copy of the request, after re-checking PayPal. Merchants write policy in plain English; Gemini compiles it into validated rules that can be simulated on past actions before saving.

**How we built it:** Python and Streamlit. PayPal Agent Toolkit for 18 PayPal tools, plus Cleat's own Payments v2 refund tool (the toolkit has none) and Subscriptions v1 cancel tool (the toolkit's drops PayPal's response). Orders v2 for refund history, Subscriptions v1 for subscription status. Gemini for the agent, the injection classifier and the policy compiler. SQLModel on SQLite, hosted on a Render web service. Held approvals expire after 24 hours.

**Challenges:** Making refund balances trustworthy (PayPal's capture endpoint has no refund total, so Cleat reads refund history from the parent order); keeping the LLM out of the decision; making a hosted demo keep working after many refunds.

**Accomplishments:** A firewall decision path that is pure, tested Python; PayPal IDs visible in every step; an over-refund blocked from PayPal's own figures whatever the customer claims.

**What we learned:** Treat every number an agent asserts as untrusted, and verify it at the source.

**What's next:** Dispute tools once the toolkit supports them, per-customer limits, and webhook-driven refund history.

**Built with:** Python, Streamlit, PayPal Agent Toolkit, PayPal Orders v2, PayPal Payments v2, PayPal Subscriptions v1, Google Gemini, LangChain, SQLModel, SQLite, Render, Claude Code (AI coding assistant).

**AI tools and how they are used:** Gemini is the support agent, the injection classifier and the policy compiler (never the decision-maker). Claude Code was used as a coding assistant; the idea, architecture, policy design and threat model were directed and reviewed by the author.

**Demo video:** https://youtu.be/qOOVDgcezs0

- Kokoro (open-source text-to-speech): AI narration voice for the demo video.
