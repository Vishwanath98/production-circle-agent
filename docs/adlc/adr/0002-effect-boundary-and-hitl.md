# ADR 0002: Durable effect boundary and standard HITL

Status: accepted.

Decision: every external effect is represented by a versioned, tenant-bound,
canonical action envelope. Policy returns ALLOW, DENY, or REQUIRE_APPROVAL.
Approval is reusable infrastructure. Only the private executor can atomically
claim an approved digest and call a provider.

Consequences: the model, MCP, x402, UI, and A2A cannot bypass approval. Reads may
be allowed directly. Retries use the original action and provider idempotency.
