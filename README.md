# Production Circle Agent

A tenant-safe, approval-gated Circle USDC agent reference implementation built
with LangGraph, MCP 2.0, policy RAG, durable state, and an optional Circle
testnet provider. The repository also includes an Onboarding agent built on the
same reusable agent spine.

The default configuration is local and deterministic. It binds to loopback,
uses SQLite, runs without paid model credentials, and cannot send a mainnet
transaction.

## What is included

- One Circle graph with explicit `core-sim`, `rag-sim`, `mcp-sim`, `full-sim`,
  `full-testnet`, and `x402-testnet` capability profiles.
- Native LangChain `@tool` definitions with model-visible schemas separated
  from server-owned identity, organization, authorization, and state context.
- Hashed and revocable development credentials, RBAC scopes, tenant-first
  database access, and adversarial cross-organization tests.
- Durable multi-turn LangGraph checkpoints, messages, action envelopes,
  approvals, audit events, idempotency records, transactions, and memories.
- Exact-digest human approval at the side-effect boundary, current-policy
  revalidation, action expiry, atomic effect claiming, and provider
  idempotency.
- Tenant-prefiltered policy RAG with citations and pinned evidence.
- Allowlisted, namespaced MCP 2.0 tools without monkey-patching.
- Circle's developer-controlled-wallet SDK adapter, signed webhook
  verification, subscription-to-tenant mapping, deduplication, and status
  reconciliation.
- Testnet-only x402 payment mapping through the same policy, approval, and
  execution boundary.
- A loopback Agent Console, REST API, Scrimmage-compatible `/chat`, and
  OpenAI-compatible `/v1/chat/completions` endpoint.
- A production-spine Onboarding agent demonstrating reuse outside payments.

## Architecture

```mermaid
flowchart LR
    Client["Agent Console / API / extractor"] --> Auth["Authentication + tenant context"]
    Auth --> Graph["One durable LangGraph"]
    Graph --> Tools["Native model tools"]
    Tools --> Policy["RBAC + policy + tenant RAG"]
    Tools --> MCP["Allowlisted MCP gateway"]
    Policy --> HITL{"Human approval required?"}
    HITL -->|deny| Audit["Redacted audit trail"]
    HITL -->|approve exact digest| Effect["Atomic idempotent effect boundary"]
    Effect --> Simulator["Deterministic simulator"]
    Effect --> Testnet["Explicit Circle testnet"]
    Testnet --> Webhook["Signed webhook reconciliation"]
    Simulator --> Audit
    Webhook --> Audit
```

The complete architecture, trust boundaries, lifecycle, and promotion gates
are documented in [`docs/adlc/`](docs/adlc/README.md).

## Quick start

Python 3.11 is required.

```bash
git clone https://github.com/Vishwanath98/production-circle-agent.git
cd production-circle-agent
python3.11 -m venv .venv
.venv/bin/pip install -e agent-spine -r circle-agent/requirements.txt
PYTHONPATH=agent-spine:circle-agent .venv/bin/python circle-agent/setup_local.py
PYTHONPATH=agent-spine:circle-agent LLM_PROVIDER=fake \
  .venv/bin/python circle-agent/serve.py
```

`setup_local.py` prints one-time local credentials for requesters and reviewers
in two test organizations. Open <http://127.0.0.1:8086>, sign in with one of
those credentials, and use `core-sim` for deterministic testing.

Rerunning setup does not mint additional credentials. Use
`--rotate-credentials` only when replacement credentials are needed. Local
state is stored under the Git-ignored `.local/` directory.

## Test with an extractor

The repository exposes several stable extraction surfaces:

| Surface | Location |
|---|---|
| Circle OpenAPI 3.1 | [`docs/api/openapi.yaml`](docs/api/openapi.yaml) |
| Served Circle OpenAPI | `GET http://127.0.0.1:8086/openapi.yaml` |
| Scrimmage chat | `POST http://127.0.0.1:8086/chat` |
| OpenAI-compatible chat | `POST http://127.0.0.1:8086/v1/chat/completions` |
| Native Circle tools | [`circle-agent/circle_agent/tools.py`](circle-agent/circle_agent/tools.py) |
| Onboarding OpenAPI 3.1 | [`docs/api/onboarding-openapi.yaml`](docs/api/onboarding-openapi.yaml) |
| ADLC build map | [`docs/adlc/build-map.md`](docs/adlc/build-map.md) |

Minimal authenticated `/chat` request:

```bash
curl -s http://127.0.0.1:8086/chat \
  -H 'Authorization: Bearer dev_REPLACE_WITH_SETUP_TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{"thread_id":"extractor-smoke","profile":"core-sim","message":"{\"action\":\"balance\"}"}'
```

For static extraction, point the extractor at the repository root or the
native tool modules above. For runtime extraction, use `/openapi.yaml` and
`/chat`; keep the generated local credential outside extractor artifacts and
logs.

## Tests

```bash
PYTHONPATH=agent-spine:circle-agent \
  .venv/bin/python -m unittest discover -s agent-spine/tests -v
PYTHONPATH=agent-spine:circle-agent \
  .venv/bin/python -m unittest discover -s circle-agent/tests -v
PYTHONPATH=agent-spine:onboarding-agent \
  .venv/bin/python -m unittest discover -s onboarding-agent/tests -v
```

The release gate currently contains 33 tests across the shared foundation,
Circle, and Onboarding. The HTTP integration tests bind only an ephemeral
loopback port. No automated test calls Circle testnet or mainnet.

## Repository layout

```text
agent-spine/       Shared auth, tenancy, state, policy, approval, MCP and RAG
circle-agent/      Unified Circle graph, providers, API, console and tests
onboarding-agent/  Shared-spine Onboarding implementation and tests
docs/adlc/         Architecture, ADRs, security model, testing and operations
docs/api/          OpenAPI 3.1 contracts
docs/schemas/      Action, approval and audit JSON Schemas
```

## Safety and production status

This is a production-oriented reference implementation, not a deployed
financial service. It contains no mainnet profile and never silently falls back
from Circle to simulation. Circle testnet and remote LangSmith tracing are
explicit opt-ins.

Before production use, complete the promotion gates in
[`docs/adlc/operations.md`](docs/adlc/operations.md), including OIDC, a
production database, managed secrets, rate limiting, SIEM integration,
distributed effect coordination, backup/restore drills, load tests, and live
Circle testnet certification.

## Documentation

- [Agent Development Lifecycle](docs/adlc/README.md)
- [Architecture](docs/adlc/architecture.md)
- [Security and tenant isolation](docs/adlc/security-and-tenancy.md)
- [Tools, tracing, and MCP](docs/adlc/tools-tracing-and-mcp.md)
- [External Circle MCP and capture/replay setup](circle-agent/README.md#external-circle-mcp)
- [RAG design](docs/adlc/rag.md)
- [x402 and A2A placement](docs/adlc/x402-and-a2a.md)
- [Testing strategy](docs/adlc/testing.md)
- [Operations and promotion](docs/adlc/operations.md)

## License

No open-source license has been granted yet. Add an explicit license only after
confirming ownership and redistribution rights for every included component.
