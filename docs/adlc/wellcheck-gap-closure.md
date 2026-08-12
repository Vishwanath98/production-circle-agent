# WellCheck gap closure

The reference WellCheck implementation was the comparison bar. Its
useful pieces were a conversational LangGraph, native `@tool` functions,
principal resolution before graph entry, tool/data-layer ownership checks,
citation-first RAG with an ungrounded path, an MCP boundary, approval before
writes, structured audit events, and stable Scrimmage thread IDs.

Circle and Onboarding now carry those concepts without copying WellCheck's
shape. They share durable principal/context/action/approval/audit infrastructure
and add controls WellCheck does not currently provide:

| Capability | WellCheck current | Local-lab Circle / Onboarding |
|---|---|---|
| Credentials | Plain demo API token in SQLite | Opaque secret shown once; scrypt hash, expiry, revocation; browser session + CSRF for Circle |
| Tenancy | Member ownership in one demo data domain | Organization on every owned record; composite keys; two-tenant adversarial tests |
| Memory | Process registry + `MemorySaver` | Durable SQLite LangGraph checkpoints and durable thread/message records |
| Approval | `interrupt_before` and runtime auto-approve option | Durable approval record bound to tenant, action version/digest, reviewer role/scope, expiry |
| Exactly once | Tool write after interrupt | Unique tenant idempotency, atomic compare-and-set claim, provider UUIDv4 key |
| RAG isolation | Local shared corpus | Global + tenant corpus with SQL authorization prefilter before scoring |
| MCP | MCP 1.x, optional transparent local fallback | MCP 2.0, explicit allowlists/namespaces/scopes/timeouts, no monkey-patch or data fallback |
| Provider failure | Local fallback available in auto mode | Effects fail closed; simulator is an explicit profile only |
| External finality | Not applicable | Circle SDK normalized states plus ECDSA-verified, tenant-mapped, deduplicated webhooks |
| API/UI | Scrimmage facade | Native REST, `/chat`, OpenAI shape, SSE audit, OpenAPI, and Circle operations console |
| Protocol expansion | None | x402 testnet through the same effect boundary; A2A seam documented above API |

WellCheck remains a useful behavioral reference, not a production security
template. In particular, its plaintext demo credentials, in-memory checkpoint,
process registry, MCP auto-fallback, and auto-approval option must not be copied
into effectful multi-tenant agents.
