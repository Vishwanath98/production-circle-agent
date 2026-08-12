# Operations and promotion

## Configuration classes

- Non-secret: profile, loopback host/port, database paths, model name, timeouts,
  MCP allowlist, fee reserve, supported networks.
- Secret: model keys, Circle API key, Circle entity secret, webhook key access,
  LangSmith key. Keep these in a secret manager or uncommitted `.env.local`.
- Tenant configuration: wallet mapping, webhook subscription mapping, roles,
  scopes, policy documents. Keep these in durable storage, not environment
  variables supplied by clients.

## Health and recovery

`/healthz` reports process liveness; `/readyz` verifies database access. Before
production, readiness must also report migration compatibility and configured
provider/MCP dependencies without making financial calls.

SQLite WAL is appropriate for the isolated lab. Production should use
PostgreSQL, transactional outbox processing for webhooks/effects, distributed
locks or serializable claims, managed backups, point-in-time recovery, and a
documented restore drill. LangGraph checkpoints and application actions must be
backed up consistently.

## Provider behavior

- Circle failures remain failures; never switch to simulation.
- A submitted transaction is not final. Poll or process signed webhooks.
- Unknown provider states remain non-final and alert operators.
- Reconciliation jobs compare provider and local transaction state.
- Stuck actions must be investigated; operators may retry only through the
  same idempotent action, never by creating an unlinked transfer.

## Promotion gates

1. All offline, integration, adversarial, and migration tests pass.
2. Threat model and data-flow review approved.
3. OIDC, production database, secrets manager, rate limits, and SIEM connected.
4. Circle sandbox exercises approval, rejection, duplicate, timeout, webhook,
   and finality paths with restricted credentials.
5. Load, concurrency, backup/restore, and dependency-failure drills pass.
6. Human runbook, incident response, key rotation, and rollback are rehearsed.
7. A separate explicit change enables any production/mainnet profile.
