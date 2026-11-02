# Demo video script (target 2:45, hard limit under 3:00)

Own voice, 1080p, no music, English. Before recording: seed orders, press **Reset demo data** on Overview, and open the PayPal sandbox dashboard in a second tab.

| Time | Screen | Say / click |
|---|---|---|
| 0:00–0:20 | Overview | "AI support agents can now issue PayPal refunds. One manipulated message can drain a small merchant. This is Cleat." Show the live URL. |
| 0:20–0:45 | README diagram | Message → injection check → agent → Cleat → PayPal sandbox. Gemini's three roles; the decision is deterministic code. |
| 0:45–1:15 | Inbox | Select **03**, Run agent. Point at PayPal-verified facts, rule R1, Allowed + Executed, refund ID. |
| 1:15–1:45 | Inbox | Run **05**: injection risk high, blocked by R4. Run **07**: "PayPal says $45 was paid", HARD-OVER-REFUND. |
| 1:45–2:10 | Inbox → Approvals → PayPal tab | Run **04** (held). Approvals: Approve. Show the refund ID, then cut once to the sandbox dashboard showing it. "Cleat executes the frozen request; the agent can't change the amount." |
| 2:10–2:30 | Policies | Add "Refunds over $150 are never allowed.", Compile, Simulate on last 20, Save. |
| 2:30–2:45 | Audit Log, Overview | Show every decision and $ protected. "Cleat. Your AI agent can be talked into anything. Your PayPal can't." |
