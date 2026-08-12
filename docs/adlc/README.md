# Circle Agent Development Life Cycle

This directory is the implementation handoff for a coding agent or engineer.
Start with `architecture.md`, then follow `build-map.md` in dependency order.
Each work package names the relevant files, invariants, and acceptance tests.

## Artifact index

- `architecture.md` — runtime boundaries and effect lifecycle.
- `build-map.md` — code-oriented component and test map.
- `security-and-tenancy.md` — threat model, auth, RBAC, tenant isolation, secrets.
- `tools-tracing-and-mcp.md` — native `@tool`, LangSmith, MCP 2.0 gateway rules.
- `rag.md` — ingestion, authorization prefilter, grounding, citations.
- `x402-and-a2a.md` — x402 placement and the deferred A2A boundary.
- `operations.md` — setup, configuration, webhooks, recovery, promotion gates.
- `testing.md` — test pyramid, adversarial matrix, and release gates.
- `onboarding-migration.md` — how Onboarding moves onto the same foundation.
- `wellcheck-gap-closure.md` — comparison bar and controls added beyond it.
- `implementation-log.md` — factual local build record.
- `adr/` — decisions that must not be silently reversed.

Machine-readable contracts live in `../api/openapi.yaml` and `../schemas/`.
