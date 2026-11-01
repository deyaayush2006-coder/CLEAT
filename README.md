# Cleat

**Your AI support agent can be talked into anything. Your PayPal can't.**

Cleat is a spending firewall for AI customer-support agents that can issue PayPal refunds. It is being built for the PayPal AI Hackathon 2026.

## Status

In development. The repository currently holds the project scaffold and one working safeguard: Cleat refuses to start unless `PAYPAL_ENV=sandbox`, and its PayPal base URL is fixed to `https://api-m.sandbox.paypal.com`.

This README only describes what works end to end, so it grows as each feature is finished.

## AI-assisted development

Cleat was built with Claude Code as a coding assistant. The product idea, architecture, policy design, threat model and all integration decisions were directed and reviewed by the author.

## Licence

MIT, see [LICENSE](LICENSE). Third-party dependencies and their licences are listed in [THIRD_PARTY.md](THIRD_PARTY.md).
