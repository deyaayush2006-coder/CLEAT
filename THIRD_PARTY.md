# Third-party software and services

Cleat's direct dependencies, as listed in `requirements.in`, at the exact versions locked in `requirements.txt` (which also pins every transitive dependency). Licences come from each package's published metadata. The PayPal Agent Toolkit publishes none, so its licence is taken from its source repository. pip also installs transitive dependencies, which carry their own licences.

The "Used for" column describes each dependency's role in Cleat's design; the README states what currently works.

| Package | Version | Used for | Licence |
|---|---|---|---|
| [paypal-agent-toolkit](https://github.com/paypal/agent-toolkit) | 1.1.0 | PayPal tools for the support agent (orders, invoices, products, plans, subscriptions); pinned because 1.11.0 renamed tools and pulls in langchain-core 0.3 | Apache-2.0 |
| langchain | 1.4.7 | Required by the toolkit's LangChain adapter | MIT |
| langchain-core | 1.7.3 | Tool definitions, tool binding and chat messages | MIT |
| langchain-google-genai | 4.4.2 | Gemini chat model | MIT |
| requests | 2.34.2 | Direct PayPal REST calls (OAuth, orders, captures, refunds) | Apache-2.0 |
| pydantic | 2.14.2 | Rule, decision and tool-argument schemas | MIT |
| sqlmodel | 0.0.48 | Storage for attempts, approvals and policy versions | MIT |
| psycopg[binary] | 3.3.6 | Postgres driver, used only if `DATABASE_URL` points to Postgres | LGPL-3.0-only |
| streamlit | 1.66.1 | The web interface | Apache-2.0 |
| python-dotenv | 1.2.4 | Loading `.env` in development | BSD-3-Clause |
| pytest | 9.2.0 | Test suite | MIT |

## Services

| Service | Used for | Terms |
|---|---|---|
| PayPal REST APIs, sandbox only ([docs](https://developer.paypal.com/api/rest/)) | Orders, captures, refunds and subscriptions | PayPal's developer terms |
| Google Gemini API | Support agent, injection classifier and policy compiler | [Gemini API Additional Terms of Service](https://ai.google.dev/gemini-api/terms) |
