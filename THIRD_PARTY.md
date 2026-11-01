# Third-party software and services

Cleat's direct dependencies, as listed in `requirements.txt`. Licences come from each package's published metadata. The PayPal Agent Toolkit publishes none, so its licence is taken from its source repository. pip also installs transitive dependencies, which carry their own licences.

The "Used for" column describes each dependency's role in Cleat's design; the README states what currently works.

| Package | Used for | Licence |
|---|---|---|
| [paypal-agent-toolkit](https://github.com/paypal/agent-toolkit) | PayPal tools for the support agent (orders, invoices, subscriptions) | Apache-2.0 |
| langchain | Required by the toolkit's LangChain adapter | MIT |
| langchain-core | Tool definitions, tool binding and chat messages | MIT |
| langchain-google-genai | Gemini chat model | MIT |
| requests | Direct PayPal REST calls (OAuth, orders, captures, refunds) | Apache-2.0 |
| pydantic | Rule, decision and tool-argument schemas | MIT |
| sqlmodel | Storage for attempts, approvals and policy versions | MIT |
| psycopg[binary] | Postgres driver for the hosted database | LGPL-3.0-only |
| streamlit | The web interface | Apache-2.0 |
| python-dotenv | Loading `.env` in development | BSD-3-Clause |
| pytest | Test suite | MIT |

## Services

| Service | Used for | Terms |
|---|---|---|
| PayPal REST APIs, sandbox only ([docs](https://developer.paypal.com/api/rest/)) | Orders, captures and refunds | PayPal's developer terms |
| Google Gemini API | Support agent, injection classifier and policy compiler | [Gemini API Additional Terms of Service](https://ai.google.dev/gemini-api/terms) |
