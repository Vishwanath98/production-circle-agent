# Circle production lab implementation log

## Baseline

- Python: 3.11.15
- Implementation date: 2026-08-12
- Public export: standalone repository with unrelated monorepo code and history
  excluded

## WP-0 findings

The baseline agent-spine tracing tests pass. The Circle offline runner is not
actually offline by default: without a provider override it constructs the
module-level Anthropic client and fails without credentials. Circle also asks
for a persistent SQLite checkpointer but silently falls back to `MemorySaver`
when the optional SQLite checkpoint package is absent.

Characterization in the source project recorded these legacy behaviors:

- exhausted insufficient balance routes to the settlement assessment;
- live Circle balance errors silently return simulated data;
- the workflow HTTP serving path drops the caller's `thread_id`;
- Circle's apparent tools are tracing wrappers, not LangChain tools;
- the MCP variant globally monkey-patches Circle base functions; and
- requested SQLite persistence may silently downgrade to memory.

The standalone public export excludes those superseded implementations and
their characterization tests so tools and extractors see one authoritative
path. Positive production-contract tests cover the replacement implementation.

## Implemented local-lab packages

- Shared foundation: hashed/revocable credentials, browser sessions, server
  runtime context, tenant-first SQLite store, durable checkpointer, action
  envelopes, policy outcomes, durable approvals, audit redaction, native tool
  catalog, tenant RAG, and MCP gateway.
- Circle: one graph with six profiles; deterministic simulator; official
  `circle-developer-controlled-wallets==9.6.0` testnet adapter; native tools;
  multi-turn HITL; tenant RAG; MCP 2.0; x402 testnet mapping; ECDSA webhook
  verification; native REST, compatibility, OpenAI-shaped API, SSE audit, and
  local operations console.
- Onboarding: one graph with four profiles; native tools; tenant applications;
  deterministic local KYB; separate onboarding policy; durable HITL account
  provisioning; tenant RAG; MCP 2.0; authenticated `/chat`, approval, and
  application API.
- Documentation: architecture and lifecycle diagrams, threat model, build map,
  tool/LangSmith rules, MCP/RAG/x402/A2A placement, operations, testing,
  WellCheck comparison, ADRs, OpenAPI contracts, and JSON schemas.

The current dependency probes on 2026-08-12 identified `mcp==2.0.0` and
`circle-developer-controlled-wallets==9.6.0` as the latest PyPI releases. They
are pinned in the isolated agent requirements. No mainnet profile or deployment
was created.

## Final local release gate

- Dependency dry-runs resolved without downloading or changing the environment.
- Shared foundation: 16 tests passed.
- Circle: 12 production tests passed, including the authenticated loopback API and
  adversarial two-organization isolation cases.
- Onboarding: 5 tests passed, including its authenticated production graph.
- Python compilation, OpenAPI YAML parsing, JSON parsing/schema validation,
  whitespace checks, tracked-secret scanning, and setup idempotency are final
  handoff gates.

The third-party LangChain 0.3.28 serializer emits a Pydantic 2.11 deprecation
warning under the currently installed Pydantic 2.13.4. It does not affect the
test result, but dependency modernization remains a production-promotion gate.
